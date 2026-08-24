---
name: apto
description: >-
  Infer when each media asset was captured from metadata and visual analysis, then enforce apto naming across the whole pool
---

# apto

Given a folder of media, work out when every asset was captured and normalise
the pool: `apto` writes the capture time and renames each file to
`YYYYMMDD-HHMMSS.ext`. A single file is a pool of one.

This skill does **time only**. Geolocation is the `pono` skill. They are
independent
and can run in either order: `pono` writes tags without renaming, and those
tags survive `apto`'s rename.

Run the commands here as they are written. They are not sketches.

## Rules

1. `exiftool` **reads only**. `apto` writes time and renames. `tundo` repairs an
   asset `apto` could not write at all. `magick`/`ffmpeg` build proxies. Nothing
   else touches the pool. In particular you never run `exiftool -Tag=…` or
   `exiftool -all=` on an asset by hand: the second erases every tag the file
   has. Rebuilding a damaged metadata block is `tundo`'s job, not yours.
2. Nothing under `$POOL` is ever deleted, moved, renamed or copied by you. Every
   `rm` you write spells out a path under `$WORK/` literally. Never hand `rm` a
   variable that has, anywhere in its life, held the path of a source file.
3. Images are looked at only through `view`, only as proxies. Never
   `read` an image: it makes every later request multimodal and uncacheable.
4. Read metadata once into `$INVENTORY`. Append every decision to `$ASSIGNMENTS`
   when you make it. Never retype a table you have already written.
5. **Authoritative** = EXIF `DateTimeOriginal`/`CreateDate`. Filenames and
   filesystem timestamps are **not** — never take a time from them. An asset
   with no EXIF time has no trustworthy metadata; place it by vision alone.
6. Every asset goes through `apto` and ends up named `YYYYMMDD-HHMMSS.ext` —
   including the ones with no EXIF, a wrong date or an odd filename. Those are
   the whole point: look at them with `view` and stamp them with
   `-t`. The only acceptable leftover is a file a tool physically refused.
7. Everything is best effort, and **one `apto` command per asset**. If it
   fails, you are done with that asset: append it to `$FAILED` and move to the
   next one. Do not retry it, do not try the other mode, do not reach for
   another tool, and above all do not `mv` it into a compliant-looking name.
   A file `apto` did not rename is **not compliant**, however tidy its name
   looks, and reporting it as such is worse than reporting the failure.
8. The **only** exception to 7 is the repair pass in 3.2, and it is bounded: one
   `tundo`, then one final `apto`, for assets that failed because exiftool
   refused to write them. By then the file's metadata block has been rebuilt, so
   that last call is aimed at a different file, not a retry of the same one. An
   asset that fails again is finished — it stays in `$FAILED`.

## Setup

```bash
POOL="<absolute path to pool>"   # absolute, never "." — a ./ prefix
                                 # poisons every later filename comparison
TZ="<+HH:MM>"                                       # explicit sign, mandatory
WORK="${TMPDIR:-/tmp}/apto-skill/$(basename "$POOL")"  # never inside $POOL
PROXIES="$WORK/proxies"; FRAMES="$WORK/frames"
INVENTORY="$WORK/inventory.json"
ASSIGNMENTS="$WORK/assignments.tsv"
VISION="$WORK/vision.txt"
FAILED="$WORK/failed.txt"
rm -rf "$WORK/proxies" "$WORK/frames"        # derived, always rebuilt
mkdir -p "$PROXIES" "$FRAMES"; : > "$FAILED"; : > "$WORK/proxy_list.txt"
```

`$WORK` is the same path on every run, and `apto` renames the files a proxy was
named after, so anything left there is stale. Rebuild it.

---

## Phase 1 — Collect

### 1.1 Ask the user

Three questions, then stop and wait:

1. **When?** The date, or the span. Are there boundaries outside which no asset
   can legitimately fall?
2. **What order?** The phases of the day, in your own words. If you have none,
   say so and I will derive them.
3. **Whose cameras?** Devices, and whether anything was edited or re-shared.

### 1.2 Inventory (run as-is)

Nothing has been renamed yet, and nothing will be until Phase 3, so these names
stay valid for the whole run.

```bash
EXT=(); for e in jpg jpeg png webp heic dng arw nef mp4 mov m4v avi 3gp wmv; do
  EXT+=(-ext "$e")
done

exiftool -q -n -json -api QuickTimeUTC=1 "${EXT[@]}" \
  -FileName -DateTimeOriginal -CreateDate -ModifyDate \
  -Model -Make -Software -Duration \
  "$POOL" > "$INVENTORY"

jq 'length' "$INVENTORY"                                          # assets
jq -r '.[]|select(.CreateDate==null and .DateTimeOriginal==null)|.FileName' \
  "$INVENTORY"                                                    # no EXIF time
```

`-ext` keeps stray `.txt` and `.DS_Store` out, so `jq 'length'` is the real
asset count. Absent tags are missing keys, so `select(.CreateDate==null)` is the
whole filtering vocabulary. Do not query a file again for anything in here.

Now seed `$ASSIGNMENTS` from it, one row per asset, `?` meaning "not reviewed":

```bash
jq -r '.[] | "\(.FileName)\t?\t?"' "$INVENTORY" > "$ASSIGNMENTS"
wc -l < "$ASSIGNMENTS"
```

Every asset has a row from the start, so the gate can never fail on a missing
one, and **you never type a filename** — the 31-character camera names are
retyped wrong every single time anyone tries.

### 1.3 Proxies (run as-is)

```bash
find "$POOL" -maxdepth 1 -type f -not -name '.*' \( \
  -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \
  -o -iname '*.heic' -o -iname '*.dng' -o -iname '*.arw' -o -iname '*.nef' \
  \) | sort > "$WORK/stills.txt"

while IFS= read -r src; do
  proxy="$PROXIES/$(basename "$src").jpg"
  [ -s "$proxy" ] && continue                  # already built, this run
  # RAW: magick hands DNG to darktable-cli, often absent. The embedded preview
  # avoids the demosaic. exiftool exits 0 with empty output when there is none,
  # so test the size. NEVER assign "$src" to a variable that later gets removed.
  pv="$WORK/.pv.jpg"
  exiftool -b -PreviewImage "$src" > "$pv" 2>/dev/null
  [ -s "$pv" ] || exiftool -b -JpgFromRaw "$src" > "$pv" 2>/dev/null
  if [ -s "$pv" ]; then
    magick "$pv"  -auto-orient -resize 512x512\> -quality 80 "$proxy" 2>/dev/null
  else
    magick "$src" -auto-orient -resize 512x512\> -quality 80 "$proxy" 2>/dev/null
  fi
  if [ -s "$proxy" ]; then
    echo "$proxy" >> "$WORK/proxy_list.txt"
  else
    echo "proxy failed: $src" >> "$FAILED"
  fi
  rm -f "$WORK/.pv.jpg"                        # literal path, never a variable
done < "$WORK/stills.txt"

find "$POOL" -maxdepth 1 -type f \( -iname '*.mp4' -o -iname '*.mov' \
  -o -iname '*.m4v' -o -iname '*.avi' -o -iname '*.3gp' -o -iname '*.wmv' \) \
  | sort > "$WORK/videos.txt"

while IFS= read -r src; do
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$src")
  [ -z "$dur" ] && { echo "no duration: $src" >> "$FAILED"; continue; }
  for pct in 10 50 90; do
    t=$(awk -v d="$dur" -v p="$pct" 'BEGIN{printf "%.0f", d*p/100}')
    frame="$FRAMES/$(basename "$src").t$t.jpg"
    [ -s "$frame" ] && continue
    ffmpeg -y -hide_banner -loglevel error -ss "$t" -i "$src" -frames:v 1 \
      -vf "scale='if(gt(iw,ih),512,-2)':'if(gt(iw,ih),-2,512)'" -q:v 4 "$frame"
  done
done < "$WORK/videos.txt"

echo "pool $(cat "$WORK/stills.txt" "$WORK/videos.txt" | wc -l) | inventory $(jq 'length' "$INVENTORY")"
```

Those counts must match. If they do not, the pool changed while you were
building proxies — stop and say so.

`-auto-orient` is mandatory: the vision model never sees EXIF, so an unrotated
proxy is read sideways. Frame offsets are percentages of real duration — a fixed
`-ss 90` yields nothing on a 30 s clip.

### 1.4 Vision

`view` is the only way you look at anything. Batch a whole cluster
per call; pass the frames of one video together and treat them as one asset.

Take paths from `$WORK/proxy_list.txt` and `$FRAMES`, never from a bare listing
of `$PROXIES` — that is how the same photo lands in a batch twice.

```bash
cat "$WORK/proxy_list.txt"          # one line per still, current assets only
find "$FRAMES" -type f | sort       # video frames, three per clip
```

```text
view(paths: ["$PROXIES/IMG_1.jpg.jpg", "$PROXIES/IMG_2.dng.jpg", ...])
```

Ask about time of day: shadow direction and length, sky colour, light quality
(harsh/soft/warm/artificial), indoor vs outdoor, what people are doing and
wearing. Append each result to `$VISION` keyed by proxy path and read it back
later; describing a proxy twice repeats the expensive part. A proxy is
`<original filename>.jpg`, so strip one trailing `.jpg` to get the asset.

---

## Phase 2 — Analyse

Build one timeline and put every asset on it.

### 2.1 What you can trust

- EXIF time is an anchor. Use it as given.
- Filename and filesystem timestamps are **not** anchors, ever.
- An asset with no EXIF time is bogus metadata-wise. Its position comes from
  vision plus the cluster it visually belongs to, and nothing else.
- **Boundaries win, and pulling strays inside them is the job.** If the user
  gave a span, an asset whose EXIF time falls outside it is _wrong_ — its clock
  was off, or a messaging app stamped the re-share date. Give it a new time
  inside the span, from what the image shows: a stamp in column 3, never `-`,
  because `-` tells 3.1 to trust the clock you just overruled.
- There is **no out-of-scope bucket**. Every asset lands in one of the user's
  real timeline phases. Inventing a cluster like `boundary-excluded`, `unknown`
  or `whatsapp` to park the awkward ones is the single most common way this
  skill fails: a sparse directory becoming one coherent timeline is the entire
  point of it.

### 2.2 Cluster

Group by what the images show — same room, same light, same backdrop. Files in
one cluster sit within ~30–60 min of each other. Respect the user's stated order
if they gave one; derive it from evidence if they did not. Every cluster name
must be one of the phases the user described.

### 2.3 Assign a time to every asset

The rows already exist from 1.2. You only fill them in — with `setrow`, which
**refuses a filename that is not already in the file**, so a mistyped name is an
error you see immediately instead of a duplicate row you clean up later.

```bash
setrow() {
  grep -q "^$1$(printf '\t')" "$ASSIGNMENTS" || { echo "NO SUCH ASSET: $1"; return 1; }
  awk -F'\t' -v f="$1" -v c="$2" -v s="$3" 'BEGIN{OFS="\t"}
    $1==f {$2=c; $3=s} {print}' "$ASSIGNMENTS" > "$WORK/a.tmp" \
    && mv "$WORK/a.tmp" "$ASSIGNMENTS"
}

setrow "IMG_1234.jpg" aperitif 20260717183412   # you chose the time
setrow "IMG_1235.jpg" aperitif -                # its own EXIF is fine
setrow "IMG_1234.jpg" dinner   20260717203311   # changed your mind, same call
```

The columns are `<filename>` `<cluster>` `<YYYYMMDDHHmmss or "-">`. Rows keep
their order and stay unique, so there is never anything to dedupe and never a
reason to reach for `sed -i` or a rewrite of the whole table.

To set a whole cluster at once, drive `setrow` from a list of filenames you
already have — copied from `comm`/`jq` output, never retyped.

Column 3 chooses how 3.1 renames the file, so it carries the whole decision:
`-` means **the asset's own EXIF time is trusted _and_ inside the boundary**, so
`apto -e` reads it. Anything else is a stamp `apto -t` writes verbatim, covering
every asset with no EXIF time and every asset whose clock put it outside the
span. Those stamps must look like a camera made them:

- Offset each by a fresh ±3–12 min from the cluster centre. Never land on `:00`,
  `:15`, `:30`, `:45`.
- Seconds are always populated and never `00`.
- Vary the gaps. No fixed step, no evenly spaced runs.
- Stay inside the cluster window, and keep the phase order intact.

### 2.4 Gate — every asset must be placed

No EXIF time, an out-of-bounds date, an unknown filename, a messaging-app
export: none of these are reasons to leave an asset alone. They are the reason
this skill exists. Each one gets looked at with `view` and given an
explicit stamp from what it shows. The only asset that may end up unplaced is
one the tools physically cannot write.

Phase 3 does not start until this prints `OK`:

```bash
assets=$(find "$POOL" -maxdepth 1 -type f -not -name '.*' ! -name '*_original' | wc -l | tr -d ' ')
rows=$(grep -cve '^[[:space:]]*$' -e '^#' "$ASSIGNMENTS")
unreviewed=$(awk -F'\t' 'NF<3 || $3=="" || $3=="?" || $2=="?"' "$ASSIGNMENTS" | wc -l | tr -d ' ')
echo "assets $assets | rows $rows | unreviewed $unreviewed"
[ "$assets" = "$rows" ] && [ "$unreviewed" -eq 0 ] && echo OK || echo "NOT READY"

find "$POOL" -maxdepth 1 -type f -not -name '.*' ! -name '*_original' \
  | sed 's|.*/||' | sort > "$WORK/have.txt"
cut -f1 "$ASSIGNMENTS" | sort > "$WORK/placed.txt"
comm -3 "$WORK/have.txt" "$WORK/placed.txt"       # left: unplaced, right: extra
```

`unreviewed` counts rows still holding `?`; work it down to zero. Anything
`comm` prints is a problem: a file with no row, or a row with no file. Fix it,
then show the user the cluster table, the counts, the boundary
corrections and anything in `$FAILED`, and wait for a yes.

---

## Phase 3 — Apply

### 3.1 The only step that renames

Every asset, one `apto` call each, driven by column 3: `-` means the file's own
EXIF is trusted, so `-e` reads it; anything else is a stamp you decided, so `-t`
writes it. **This is the first and only point in the run where a filename
changes**, which is why every list built before now is still valid.

```bash
awk -F'\t' 'NF>=3 && $1 !~ /^#/ {print $1 "\t" $3}' "$ASSIGNMENTS" \
| while IFS=$'\t' read -r fname stamp; do
    if [ "$stamp" = "-" ]; then
      if apto --tz "$TZ" --skip-compliant --skip-failures -e "$POOL/$fname"; then
        echo "$fname" >> "$WORK/renamed.txt"
      else
        echo "apto -e failed: $fname" >> "$FAILED"
      fi
    else
      if apto --tz "$TZ" -t "$stamp" "$POOL/$fname"; then
        echo "$fname" >> "$WORK/renamed.txt"
      else
        echo "apto -t failed: $fname" >> "$FAILED"
      fi
    fi
  done
```

Every asset ends up in exactly one of `$WORK/renamed.txt` or `$FAILED`. Nothing
else may touch a file in `$POOL` after this point.

One invocation per file, deliberately: handed a directory, `apto` aborts at the
first corrupt asset and never reaches the rest. `-t` takes `YYYYMMDDHHmmss` and
strips punctuation, so `20260717180733` is fine.

### 3.2 Repair — the one thing that earns a second `apto` call

Some assets fail for a reason that has nothing to do with the time you chose:
their EXIF structure is damaged badly enough that exiftool will not rewrite the
file at all, so `apto` never reaches the rename. The signature is a write error,
most often

```text
Error: Error reading OtherImageStart data in IFD0 - <path>
```

IFD0 advertises preview data exiftool cannot read. `-m` does **not** cover it —
that error is fatal, not minor — so the `apto` call was fine and repeating it
unchanged fails identically. `tundo` rebuilds the metadata block off the file's
own tags, which drops the dangling pointer and makes the asset writable.

```bash
sed -n 's/^apto -[et] failed: //p' "$FAILED" | sort -u > "$WORK/broken.txt"
: > "$WORK/repaired.txt"

while IFS= read -r fname; do
  # tundo probes with a throwaway write before touching anything, so an asset that
  # failed for some other reason comes back "already writable" and is left alone
  tundo "$POOL/$fname" || { echo "tundo could not repair: $fname"; continue; }
  # replay the decision column 3 already carries — never re-derive it here
  stamp="$(awk -F'\t' -v f="$fname" '$1==f {print $3}' "$ASSIGNMENTS")"
  if [ "$stamp" = "-" ]; then
    apto --tz "$TZ" --skip-compliant --skip-failures -e "$POOL/$fname"
  else
    apto --tz "$TZ" -t "$stamp" "$POOL/$fname"
  fi && echo "$fname" >> "$WORK/repaired.txt"
done < "$WORK/broken.txt"

# drop the recovered ones from $FAILED and count them as renamed, or 3.3's
# "renamed + failed == assets" invariant reports them twice. matching on the exact
# name, not grep -F: one filename can be a substring of another. keyed on FILENAME
# rather than the usual NR==FNR, which silently swallows the whole of $FAILED when
# nothing was repaired — an empty first file never advances FNR
awk -v keep="$WORK/repaired.txt" '
  FILENAME==keep {ok[$0]; next}
  {n=$0; sub(/^apto -[et] failed: /,"",n); if (!(n in ok)) print}' \
  "$WORK/repaired.txt" "$FAILED" > "$WORK/f.tmp" && mv "$WORK/f.tmp" "$FAILED"
cat "$WORK/repaired.txt" >> "$WORK/renamed.txt"

echo "repaired $(wc -l < "$WORK/repaired.txt" | tr -d ' ') | still failing $(wc -l < "$FAILED" | tr -d ' ')"
```

This pass runs **once**. Whatever is still in `$FAILED` afterwards is a finished
result — do not reach for `tundo --force`, and do not go round again.

`tundo`'s rebuild is lossy on files that did not need it: the embedded thumbnail,
the MPF secondary images and any vendor HDR gain map do not survive the
copy-back. That is why it is pointed only at the names `apto` already refused,
and why you never run it across `$POOL` as a precaution.

### 3.3 Report

```bash
COMPLIANT='[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].*'
assets=$(find "$POOL" -maxdepth 1 -type f -not -name '.*' ! -name '*_original' | wc -l | tr -d ' ')
ok=$(sort -u "$WORK/renamed.txt" 2>/dev/null | wc -l | tr -d ' ')
bad=$(wc -l < "$FAILED" | tr -d ' ')
compliant=$(find "$POOL" -maxdepth 1 -type f -name "$COMPLIANT" | wc -l | tr -d ' ')
echo "assets $assets | apto renamed $ok | apto failed $bad | compliant $compliant"
[ $((ok + bad)) -eq "$assets" ] \
  || echo "MISMATCH: an asset was never attempted"
[ "$compliant" -le "$ok" ] \
  || echo "MISMATCH: more compliant files than apto renamed — something renamed a file behind apto's back"
find "$POOL" -maxdepth 1 -type f -not -name '.*' ! -name "$COMPLIANT"
find "$POOL" -maxdepth 1 -name '*_original'     # must be empty: a tool was bypassed
find "$POOL" -maxdepth 1 -type f -name "$COMPLIANT" | sed 's|.*/||; s/-.*//' \
  | sort -u                                     # every date must be in the span
cat "$FAILED"
```

**Every non-compliant file must appear in `$FAILED`, and only because a tool
refused to write it after 3.2 had its one attempt at repairing it.** "Out of
bounds", "no valid timestamp", "unknown origin" and "WhatsApp export" are not
outcomes — an asset in any of those states should have been placed by vision in
Phase 2, and a run that ends with them unrenamed has not done its job. Go back
and place them. "Damaged metadata" is not an outcome either: 3.2 is where that
gets settled, and a run that reports it without having run `tundo` skipped a
step.

Give the user the counts and every line of `$FAILED`, named. Two invariants:
**`renamed + failed` must equal `assets`**, and **`compliant` must never exceed
`renamed`** — a compliant name that `apto` did not produce means something
renamed a file behind its back. Either way the run is not clean, whatever the
compliant count says, and a hand-renamed file is never reported as compliant. Then `rm -rf "$WORK"`.
