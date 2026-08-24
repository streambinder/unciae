/**
 * vision-offload — look at images without putting them in the conversation.
 *
 * mlx-serve bypasses its prefix cache entirely for any request carrying an image:
 * byte-identical repeats still report cached_tokens 0, and prefill cost scales
 * ~ctx^1.56. So one image read into a 43k-token agent context costs 44-127 s AND
 * poisons every later turn of that session, while the same image analysed in a
 * throwaway ~250-token context costs 0.7 s.
 *
 * view runs each file through a one-shot model call with no history and
 * no tools, and hands back text.
 *
 * This extension only ADDS a tool -- it never blocks or rewrites anything, so it is
 * inert in sessions that do not call it. Keeping images out of a context is the
 * caller's job: `pi -xt read` removes the tool route, and pi's own
 * `images.blockImages` setting covers the rest (`@file` attachments and any other
 * tool returning an image). Neither affects view, which calls the provider
 * directly rather than through the agent's context conversion.
 */

import { readFile } from "node:fs/promises";
import type { AssistantMessage, Usage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const DEFAULT_BRIEF = [
  "You are a vision feature extractor. Report only what is observable in the image.",
  "Never guess a city, building or landmark. Be terse: facts, no prose, no preamble.",
].join(" ");

const DEFAULT_QUESTION = [
  "Report, one short line each: indoor/outdoor; sky colour; light quality (harsh direct,",
  "soft diffused, warm, artificial); shadow direction and length; any legible clock,",
  "screen, departure board or dated signage (quote it verbatim, else 'none');",
  "people count and posture; clothing and apparent season; objects and setting.",
].join(" ");

const MAX_TOKENS = 400;

// magic bytes, not extensions: pi's read tool sniffs content too, so a .dat holding
// a JPEG would otherwise slip past an extension-only gate
const SIGNATURES: Array<[string, (b: Buffer) => boolean]> = [
  ["image/jpeg", (b) => b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff],
  [
    "image/png",
    (b) =>
      b
        .subarray(0, 8)
        .equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])),
  ],
  ["image/gif", (b) => b.subarray(0, 6).toString("latin1").startsWith("GIF8")],
  [
    "image/webp",
    (b) =>
      b.subarray(0, 4).toString("latin1") === "RIFF" &&
      b.subarray(8, 12).toString("latin1") === "WEBP",
  ],
  ["image/bmp", (b) => b[0] === 0x42 && b[1] === 0x4d],
];

const sniffMimeType = (buffer: Buffer): string | undefined =>
  SIGNATURES.find(([, test]) => test(buffer))?.[0];

const addUsage = (total: Usage, delta: Usage | undefined): Usage =>
  !delta
    ? total
    : {
        ...total,
        input: total.input + (delta.input ?? 0),
        output: total.output + (delta.output ?? 0),
        cacheRead: total.cacheRead + (delta.cacheRead ?? 0),
        cacheWrite: total.cacheWrite + (delta.cacheWrite ?? 0),
      };

const textOf = (message: AssistantMessage): string =>
  message.content
    .filter(
      (part): part is { type: "text"; text: string } => part.type === "text",
    )
    .map((part) => part.text.trim())
    .join("\n")
    .trim();

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "view",
    label: "View",
    description: [
      "Analyse image files in a throwaway context and return text descriptions.",
      "The images never enter this conversation, so this context stays cacheable.",
      "Files are processed one at a time; pass them all in a single call.",
    ].join(" "),
    promptSnippet: "Analyse images out-of-context and return text descriptions",
    promptGuidelines: [
      "Use view rather than read for every image: reading an image into the conversation makes every later request uncacheable.",
      "Batch every image you need into one view call rather than one call per file.",
    ],
    parameters: Type.Object({
      paths: Type.Array(Type.String(), {
        description:
          "Absolute paths to jpg/png/gif/webp/bmp files, processed in order",
        minItems: 1,
      }),
      question: Type.Optional(
        Type.String({
          description: `What to report about each image. Default: ${DEFAULT_QUESTION}`,
        }),
      ),
    }),

    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const model = ctx.model;
      if (!model) throw new Error("view: no active model");
      if (!model.input.includes("image"))
        throw new Error(
          `view: ${model.provider}/${model.id} is not a vision model`,
        );

      const question = params.question?.trim() || DEFAULT_QUESTION;
      const sections: string[] = [];
      let usage: Usage = {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        cost: { total: 0 },
      } as Usage;

      // strictly serial: measured 0.97x at 2 threads and 0.92x at 4 against a single
      // mlx-serve instance, so fan-out only adds contention
      for (const [index, path] of params.paths.entries()) {
        if (signal?.aborted) break;
        onUpdate?.({
          content: [
            {
              type: "text",
              text: `${sections.join("\n\n")}\n\n[${index + 1}/${params.paths.length}] ${path}`,
            },
          ],
        });

        try {
          const buffer = await readFile(path);
          const mimeType = sniffMimeType(buffer);
          if (!mimeType) throw new Error("not a jpg/png/gif/webp/bmp file");

          const response = await ctx.modelRegistry.complete(
            model,
            {
              systemPrompt: DEFAULT_BRIEF,
              messages: [
                {
                  role: "user",
                  content: [
                    { type: "text", text: question },
                    {
                      type: "image",
                      data: buffer.toString("base64"),
                      mimeType,
                    },
                  ],
                  timestamp: Date.now(),
                },
              ],
            },
            { signal, maxTokens: MAX_TOKENS, temperature: 0 },
          );

          usage = addUsage(usage, response.usage);
          sections.push(`## ${path}\n${textOf(response) || "(no output)"}`);
        } catch (error) {
          sections.push(
            `## ${path}\nERROR: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }

      return {
        content: [{ type: "text", text: sections.join("\n\n") }],
        details: { count: params.paths.length, question },
        // nested usage: keeps the vision tokens visible in session accounting
        // without them counting as parent context
        usage,
      };
    },
  });
}
