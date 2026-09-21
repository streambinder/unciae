---
name: aduno
description: >-
  Cluster near-duplicate media assets by fingerprint similarity plus vision, file each group into its own slug folder, and mark the best one recommended
---

# aduno

Given a folder of media, find the near-duplicates — files so close a human
would call them the same shot — and file each group into its own folder:
group `$GROUP` lives at `$POOL/$GROUP/`, members keep their names as
`$GROUP/$ORIGINALFILENAME`, and the best one becomes
`$GROUP/recommended-$ORIGINALFILENAME`. Files with no duplicates are
singletons and stay at the pool root, untouched. A single file is a group
of one.

This skill does **dedup only**. Capture time and naming are the `apto` skill,
geolocation is the `pono` skill. Run `aduno` **last**: grouped files sit one
level down, outside `apto`'s top-level view, and `pono` tags survive the move
untouched.

Run the commands here as they are written. They are not sketches.

## Rules

1. `exiftool` **reads only**. `magick`/`ffmpeg` build proxies, thumbs and
   frames. `sha256sum` finds exact duplicates. Nothing else touches the pool.
   The **only** pool mutation is the `mv` loop in 3.1, driven strictly from
   `$CLUSTERS` — never a hand-typed name, never a retry, never anything else.
2. Nothing under `$POOL` is ever deleted or copied by you. Every `rm` you write
   spells out a path under `$WORK/` literally. Never hand `rm` a variable that
   has, anywhere in its life, held the path of a source file.
3. Bulk vision means reading proxies inline with the read tool, and only for
   the candidate pairs 1.4 produced — never the whole pool. Exact duplicates
   need no vision: identical bytes need no second opinion. The final pick
   inside a group re-reads up to three proxies inline when the verdicts tie.
4. Read metadata once into `$INVENTORY`. Map every thumb in `$THUMBMAP` when
   you build it. Append every decision to `$CLUSTERS` when you make it. Never
   retype a table you have already written — and never `cat` one either. Query
   them instead: `jq` a field, `grep` a key, `wc -l` a count.
5. **Singletons stay untouched.** A file with no near-duplicate keeps its exact
   name. Grouping everything into forced pairs to look thorough is the most
   common way this skill fails.
6. Subfolders are skill output: a `$POOL/<dir>/` holding grouped files is
   left alone. A rerun scans top-level files only — it never re-clusters,
   moves, or nests grouped files, and never creates a folder inside a folder.
   To redo a group, move its files back to the root by hand first — there is
   no ungroup mode.
7. The folder shape is fixed: members move to `$GROUP/$ORIG`, the pick to
   `$GROUP/recommended-$ORIG`, where `$ORIG` is the full current filename and
   `$GROUP` the bare ledger slug. `$GROUP` is lowercase ASCII with hyphens,
   ≤32 chars, and never contains `/`: moves land exactly one level down, so
   nothing can ever be double-filed.
8. Everything is best effort, and **one `mv` per asset**. If it fails, append
   it to `$FAILED` and move on. Do not retry, do not reach for another tool,
   and above all do not hand-rename a file into a grouped-looking name. A file
   the loop did not move is **not grouped**, however tidy its name looks.
9. **Aesthetic wins.** The recommended file is the best-looking one: eyes open,
   best expression and framing, no blink, no motion blur, no half-covered
   face. Pixel counts and sharpness scores only pre-rank the shortlist — when
   they disagree with what the picture shows, the picture wins. When no frame
   is reasonably crownable, crown nothing: the group stays members-only (2.3).
10. **A group holds stills or video, never both.** A video clip and a photo of
    the same moment are two groups, not one — even when their frames look
    identical. 1.4 drops cross-type candidate pairs before vision ever sees
    them, and the 2.4 gate rejects any mixed group outright.
11. **Never reimplement a step's command to save time.** The 1.4 loop looks
    slow; rewriting it in another language feels clever and is the most
    dangerous thing in this skill. Reimplementations silently change units —
    one real failure kept only pixel-identical pairs because an unnormalized
    score was compared against the normalized threshold, dropping hundreds of
    real duplicates with a green gate. Run the loop as written, in the
    background if needed. The planted control in 1.4 exists to catch exactly
    this: if it fails, the loop is broken, not slow — report, do not rewrite.
12. **Media tools hang.** If any loop adds nothing to `$WORK` for 15 minutes
    while a `magick`/`ffmpeg`/`exiftool` process is still alive, that process
    is hung on one file, not working: kill it, log `hung: <file>` to `$FAILED`
    and continue with the next file. A hung file clusters with nothing, same
    as a thumb failure in 1.4. Never wait out a silent tool.

## Setup

```bash
POOL="<absolute path to pool>"   # absolute, never "." — a ./ prefix
                                 # poisons every later filename comparison
WORK="${TMPDIR:-/tmp}/aduno-skill/$(basename "$POOL")"  # never inside $POOL
PROXIES="$WORK/proxies"; THUMBS="$WORK/thumbs"; FRAMES="$WORK/frames"
INVENTORY="$WORK/inventory.json"
THUMBMAP="$WORK/thumbmap.tsv"
CANDIDATES="$WORK/candidates.tsv"
CLUSTERS="$WORK/clusters.tsv"
VISION="$WORK/vision.txt"
FAILED="$WORK/failed.txt"
rm -rf "$WORK/proxies" "$WORK/thumbs" "$WORK/frames"  # derived, rebuilt
mkdir -p "$PROXIES" "$THUMBS" "$FRAMES"
: > "$FAILED"; : > "$THUMBMAP"; : > "$CANDIDATES"
```

---

## Phase 1 — Collect

### 1.1 Ask the user

One question, then stop and wait:

1. **Known distincts?** Any bursts, brackets or sequences that look alike but
   must stay separate? Unattended, with no user answering: the answer is none
   — proceed, and quote that assumption at the gate.

The near-duplicate bar is fixed, not tunable — strict, always:

```bash
THRESH=0.05   # strict: near-identical frames count; reframings do not
```

### 1.2 Inventory (run as-is)

```bash
find "$POOL" -maxdepth 1 -type f -not -name '.*' \( \
  -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \
  -o -iname '*.heic' -o -iname '*.heif' -o -iname '*.tif' -o -iname '*.tiff' \
  -o -iname '*.dng' -o -iname '*.arw' -o -iname '*.nef' -o -iname '*.nrw' \
  -o -iname '*.cr2' -o -iname '*.cr3' -o -iname '*.rw2' -o -iname '*.raf' \
  -o -iname '*.orf' -o -iname '*.pef' -o -iname '*.srw' \
  -o -iname '*.mp4' -o -iname '*.mov' -o -iname '*.m4v' -o -iname '*.avi' \
  -o -iname '*.3gp' -o -iname '*.wmv' -o -iname '*.mkv' -o -iname '*.mpg' \
  -o -iname '*.mpeg' -o -iname '*.m2ts' \) | sort > "$WORK/top.txt"

tr '\n' '\0' < "$WORK/top.txt" | xargs -0 exiftool -q -n -json \
  -api QuickTimeUTC=1 \
  -FileName -ImageWidth -ImageHeight -FileSize -Duration \
  > "$INVENTORY"

jq 'length' "$INVENTORY"                                     # top-level assets
jq -r '.[].FileName' "$INVENTORY" | sort > "$WORK/have.txt"
find "$POOL" -mindepth 1 -maxdepth 1 -type d -not -name '.*' | sort \
  > "$WORK/subdirs.txt"                                      # prior groups
find "$POOL" -mindepth 2 -type f | wc -l                     # grouped files
```

Subdirectories of `$POOL` are previous output: grouped files live one level
down and are never scanned, moved, or re-clustered. Everything below covers
top-level files only.

```bash
jq -r '.[].FileName' "$INVENTORY" | sort > "$WORK/todo.txt"
wc -l < "$WORK/todo.txt"                                          # to cluster
```

Seed `$CLUSTERS` from it, one row per asset, `single` meaning "no duplicate
found yet":

```bash
jq -r '.[] | "\("?")\t\(.FileName)\tsingle\t-"' \
  "$INVENTORY" > "$CLUSTERS"
wc -l < "$CLUSTERS"
```

Column 1 is the group (`?` = unreviewed), column 2 the filename, column 3 the
role (`single`, `member`, `recommended`), column 4 a one-phrase note. **You
never type a filename** — every later helper refuses names not already here.

Helpers (run as-is, use for every edit):

```bash
slug() {  # normalise a group name: lowercase ascii, hyphens, ≤32 chars
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | iconv -f utf8 -t ascii//TRANSLIT 2>/dev/null \
    | tr -cs 'a-z0-9' '-' | sed -e 's/^-//' -e 's/-$//' | cut -c1-32
}
setgrp() {  # set group of an existing row, refuse unknown filenames
  awk -F'\t' -v f="$1" '$2==f{found=1} END{exit !found}' "$CLUSTERS" \
    || { echo "NO SUCH ASSET: $1"; return 1; }
  awk -F'\t' -v f="$1" -v g="$2" -v r="$3" -v n="$4" 'BEGIN{OFS="\t"}
    $2==f {$1=g; $3=r; $4=n} {print}' "$CLUSTERS" > "$WORK/c.tmp" \
    && mv "$WORK/c.tmp" "$CLUSTERS"
}
isvid() {  # true iff the filename is a video asset (rule 10)
  case "$1" in
    *.mp4|*.MP4|*.mov|*.MOV|*.m4v|*.M4V|*.avi|*.AVI|*.3gp|*.3GP|*.wmv|*.WMV|\
*.mkv|*.MKV|*.mpg|*.MPG|*.mpeg|*.MPEG|*.m2ts|*.M2TS) return 0 ;;
    *) return 1 ;;
  esac
}
setrec() {  # crown the pick: demotes the group's previous recommended
  g="$(awk -F'\t' -v f="$1" '$2==f {print $1}' "$CLUSTERS")"
  awk -F'\t' -v g="$g" -v f="$1" -v n="$2" 'BEGIN{OFS="\t"}
    $1==g && $3=="recommended" {$3="member"}
    $2==f {$3="recommended"; $4=n} {print}' "$CLUSTERS" > "$WORK/c.tmp" \
    && mv "$WORK/c.tmp" "$CLUSTERS"
}
```

### 1.3 Exact duplicates — no vision

Identical bytes are one group without debate:

```bash
while IFS= read -r f; do sha256sum "$POOL/$f"; done \
  < "$WORK/todo.txt" | sort > "$WORK/hashes.txt"
awk '{print $1}' "$WORK/hashes.txt" | uniq -d > "$WORK/duphash.txt"
echo "exact-dupe groups $(wc -l < "$WORK/duphash.txt" | tr -d ' ')"
```

For each hash in `$WORK/duphash.txt`, take its filenames from `$WORK/hashes.txt`
and `setgrp` them to one group with role `member` — the pick comes in 2.3.
These files skip 1.4–1.6 entirely.

### 1.4 Near-duplicate candidates (run as-is)

One 16×16 grey thumb per asset; pairwise RMSE below `$THRESH` becomes a
candidate pair. Video contributes its middle frame, treated as a still from
here on.

```bash
while IFS= read -r f; do
  src="$POOL/$f"; th="$THUMBS/$f.thumb.png"
  case "$src" in
    *.mp4|*.MP4|*.mov|*.MOV|*.m4v|*.M4V|*.avi|*.AVI|*.3gp|*.3GP|*.wmv|*.WMV|*.mkv|*.MKV|*.mpg|*.MPG|*.mpeg|*.MPEG|*.m2ts|*.M2TS)
      dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$src")
      [ -z "$dur" ] && { echo "no duration: $f" >> "$FAILED"; continue; }
      t=$(awk -v d="$dur" 'BEGIN{printf "%.0f", d/2}')
      fr="$FRAMES/$f.mid.jpg"
      ffmpeg -y -hide_banner -loglevel error -ss "$t" -i "$src" -frames:v 1 \
        -vf "scale='if(gt(iw,ih),256,-2)':'if(gt(iw,ih),-2,256)'" -q:v 5 "$fr" \
        && src="$fr" ;;
  esac
  # RAW: dodge the demosaic via the embedded preview, else convert directly
  pv="$WORK/.pv.jpg"
  exiftool -b -PreviewImage "$POOL/$f" > "$pv" 2>/dev/null
  [ -s "$pv" ] || exiftool -b -JpgFromRaw "$POOL/$f" > "$pv" 2>/dev/null
  [ -s "$pv" ] && src="$pv"
  magick "$src" -auto-orient -resize 16x16! -colorspace Gray -depth 8 "$th" \
    2>/dev/null || { echo "thumb failed: $f" >> "$FAILED"; continue; }
  printf '%s\t%s\n' "$(basename "$th")" "$f" >> "$THUMBMAP"
  rm -f "$WORK/.pv.jpg"                        # literal path, never a variable
done < "$WORK/todo.txt"
```

```bash
# control: a planted near-dupe with a known score. The loop below must find
# it at that score — if it does not, the loop is broken (rule 11), not slow.
seed=$(head -n1 "$THUMBMAP" | cut -f1)
cp "$THUMBS/$seed" "$THUMBS/CONTROL-A.thumb.png"
magick "$THUMBS/CONTROL-A.thumb.png" -modulate 103 "$THUMBS/CONTROL-B.thumb.png" 2>/dev/null
exp=$(magick compare -metric RMSE "$THUMBS/CONTROL-A.thumb.png" "$THUMBS/CONTROL-B.thumb.png" null: 2>&1 \
  | sed -n 's/.*(\([0-9.]*\)).*/\1/p')
awk -v v="$exp" -v t="$THRESH" 'BEGIN{exit !(v+0 > 0 && v+0 < t+0)}' \
  && printf 'CONTROL-A.thumb.png\tCONTROL-A\nCONTROL-B.thumb.png\tCONTROL-B\n' >> "$THUMBMAP" \
  && echo "control planted, expected $exp" \
  || echo "CONTROL OUT OF RANGE ($exp): nudge -modulate to 102 or 104 and repeat this block until 0 < expected < $THRESH"
```

Then every pair, one line per candidate:

```bash
cut -f1 "$THUMBMAP" | sort > "$WORK/thumblist.txt"
awk '{a[NR]=$0} END{for(i=1;i<=NR;i++)for(j=i+1;j<=NR;j++)print a[i]"\t"a[j]}' \
  "$WORK/thumblist.txt" > "$WORK/pairs.txt"
echo "pairs $(wc -l < "$WORK/pairs.txt" | tr -d ' ')"
: > "$CANDIDATES"
i=0
while IFS=$'\t' read -r x y; do
  i=$((i+1)); [ $((i % 5000)) -eq 0 ] && echo "pairs $i scanned"
  m=$(magick compare -metric RMSE "$THUMBS/$x" "$THUMBS/$y" null: 2>&1)
  n=$(echo "$m" | sed -n 's/.*(\([0-9.]*\)).*/\1/p')
  awk -v v="$n" -v t="$THRESH" 'BEGIN{exit !(v+0 < t+0)}' \
    && printf '%s\t%s\t%s\n' "$x" "$y" "$n" >> "$CANDIDATES"
done < "$WORK/pairs.txt"
wc -l < "$CANDIDATES"                                         # candidate pairs
```

A group holds stills or video, never both (rule 10) — drop cross-type pairs
now, so vision is never asked to confirm a group the gate would reject:

```bash
: > "$WORK/same.tsv"; : > "$WORK/dropped.tsv"
while IFS=$'\t' read -r x y n; do
  a=$(grep -m1 "^$x$(printf '\t')" "$THUMBMAP" | cut -f2)
  b=$(grep -m1 "^$y$(printf '\t')" "$THUMBMAP" | cut -f2)
  if isvid "$a"; then
    isvid "$b" || { printf '%s\t%s\tcross-type\n' "$a" "$b" >> "$WORK/dropped.tsv"; continue; }
  else
    isvid "$b" && { printf '%s\t%s\tcross-type\n' "$a" "$b" >> "$WORK/dropped.tsv"; continue; }
  fi
  printf '%s\t%s\t%s\n' "$x" "$y" "$n" >> "$WORK/same.tsv"
done < "$CANDIDATES"
mv "$WORK/same.tsv" "$CANDIDATES"
wc -l < "$CANDIDATES"                                # same-type candidate pairs
wc -l < "$WORK/dropped.tsv"                          # dropped, with reasons
```

The loop must reproduce the control at its planted score — same command on
the same files, so any other outcome means the loop diverged:

```bash
got=$(awk -F'\t' '$1=="CONTROL-A.thumb.png" && $2=="CONTROL-B.thumb.png" {print $3}' "$CANDIDATES")
if awk -v e="$exp" -v g="$got" -v t="$THRESH" 'BEGIN{ok=(g!="" && g+0>0 && g+0<t+0 && (g-e)<0.005 && (e-g)<0.005); exit !ok}'; then
  awk -F'\t' '$1 !~ /^CONTROL-/ && $2 !~ /^CONTROL-/' "$CANDIDATES" > "$WORK/c.tmp" || true
  mv "$WORK/c.tmp" "$CANDIDATES"
  grep -v '^CONTROL-' "$THUMBMAP" > "$WORK/t.tmp" || true
  mv "$WORK/t.tmp" "$THUMBMAP"
  rm -f "$THUMBS/CONTROL-A.thumb.png" "$THUMBS/CONTROL-B.thumb.png"
  echo "control OK: loop reported $got, expected $exp"
else
  echo "CONTROL FAILED (expected $exp, loop reported [$got]): the compare loop is broken. Do not reimplement it, do not tune it, do not proceed to 1.5 — report this line."
fi
```

`$CANDIDATES` holds thumb names — resolve to assets via `$THUMBMAP`, never by
stripping suffixes by hand. Above ~400 assets the pair count passes 80k and
this loop gets slow: say so and agree a reduced scope (a subfolder, or one
media type) before running it. If no user is there to agree — an unattended
run, a subagent, a background job — do not run the full cartesian and do not
reimplement the loop to cope (rule 11): split `$WORK/todo.txt` into shards of
at most 200 assets, run 1.4–1.6 per shard with only that shard's rows in play,
then continue 2.x on the union of the shards' `$CANDIDATES`. Pairs across
shards are never compared — report the shard map and that blind spot at the
gate. Sharding misses cross-shard duplicates; reimplementing loses worse.

An asset whose thumb failed (a line in `$FAILED`, e.g. a RAW with no embedded
preview and no decode delegate) cannot be compared, so it clusters with
nothing: `setgrp` it to group `-` with role `single` and note `thumb-failed`.
It counts as placed, and the `$FAILED` line stays as the reason.

### 1.5 Proxies for candidates only

Only files named in `$CANDIDATES` (plus one representative per exact-dupe
group, for the slug) get a 512px proxy. The rest of the pool never enters
vision — that is what keeps a local model alive at pool scale.

```bash
: > "$WORK/candassets.txt"
while IFS=$'\t' read -r x y _; do
  grep -m1 "^$x$(printf '\t')" "$THUMBMAP" | cut -f2 >> "$WORK/candassets.txt"
  grep -m1 "^$y$(printf '\t')" "$THUMBMAP" | cut -f2 >> "$WORK/candassets.txt"
done < "$CANDIDATES"
sort -u "$WORK/candassets.txt" -o "$WORK/candassets.txt"
while IFS= read -r f; do
  case "$f" in
    *.mp4|*.MP4|*.mov|*.MOV|*.m4v|*.M4V|*.avi|*.AVI|*.3gp|*.3GP|*.wmv|*.WMV|*.mkv|*.MKV|*.mpg|*.MPG|*.mpeg|*.MPEG|*.m2ts|*.M2TS)
      continue ;;  # video has no magick proxy: its frames below are the proxy
  esac
  proxy="$PROXIES/$f.jpg"
  [ -s "$proxy" ] && continue
  pv="$WORK/.pv.jpg"
  exiftool -b -PreviewImage "$POOL/$f" > "$pv" 2>/dev/null
  [ -s "$pv" ] || exiftool -b -JpgFromRaw "$POOL/$f" > "$pv" 2>/dev/null
  if [ -s "$pv" ]; then
    magick "$pv" -auto-orient -resize 512x512\> -quality 80 "$proxy" 2>/dev/null
  else
    magick "$POOL/$f" -auto-orient -resize 512x512\> -quality 80 "$proxy" \
      2>/dev/null || echo "proxy failed: $f" >> "$FAILED"
  fi
  rm -f "$WORK/.pv.jpg"
done < "$WORK/candassets.txt"
```

Candidate videos additionally get their 10% and 90% frames beside the middle
one 1.4 already extracted — pass all three together and treat them as one
asset. The offset is clamped inside the clip: on a short clip a raw percentage
rounds to EOF and `ffmpeg` writes nothing.

```bash
grep -Ei '\.(mp4|mov|m4v|avi|3gp|wmv|mkv|mpg|mpeg|m2ts)$' "$WORK/candassets.txt" \
| while IFS= read -r f; do
  dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$POOL/$f")
  for pct in 10 90; do
    t=$(awk -v d="$dur" -v p="$pct" \
      'BEGIN{t=d*p/100; if(t>d-1)t=d-1; if(t<0)t=0; printf "%.0f", t}')
    ffmpeg -y -hide_banner -loglevel error -ss "$t" -i "$POOL/$f" -frames:v 1 \
      -vf "scale='if(gt(iw,ih),512,-2)':'if(gt(iw,ih),-2,512)'" -q:v 4 \
      "$FRAMES/$f.$pct.jpg" \
      || echo "frame failed: $f.$pct" >> "$FAILED"
  done
done
```

### 1.6 Vision — confirm or split

```text
read(path: "$PROXIES/<file-a>.jpg")
read(path: "$PROXIES/<file-b>.jpg")
...
```

Read one candidate pair (or one star of pairs sharing a file) per batch and
ask one question: same moment, same subject, same framing — duplicates — or
distinct shots that must stay separate? Quote the user's 1.1 known-distincts
back at the model where relevant. Append each verdict to `$VISION`
**immediately, batch by batch** — never hold verdicts in memory across
batches. One tab-separated line per pair, keyed by the two asset names; when
a whole star is confirmed at once, one line per pair in it, or one line keyed
by the batch listing every member plus the verdict and any exclusions
(`comp-3 DUPLICATE a|b|c SPLIT d: reframing`). The 2.1 merge reads this file,
not your memory of the pictures.

Read it back one verdict at a time with the `vis()` helper from the `apto`
skill. Never `cat "$VISION"`.

If the run stops anywhere in 1.4–1.6, resume from disk, never from scratch:
re-running a loop rebuilds its files. The thumb loop appends to `$THUMBMAP`,
so truncate it first (`: > "$THUMBMAP"`) and rerun — thumbs rebuild over
themselves. The pairs loop truncates `$CANDIDATES` itself. The proxy loop
skips existing proxies. Nothing already written is ever re-derived by hand.

---

## Phase 2 — Analyse

### 2.1 Form groups

Merge rule: pairs sharing a file join into one group **unless** a `$VISION`
verdict calls them distinct — then they split at that edge. Exact-dupe sets
from 1.3 join unconditionally. Cross-type pairs never reach you (1.4 drops
them), and a still and a video never share a group even by hand: the gate
rejects it. A confirmed singleton — no candidates at all,
or a group of one after a split — gets group `-` with role `single` and note
`singleton`: `-` means "no group", so the gate counts it as placed and the
rename skips it.

Record each group with `setgrp`, role `member`, note `exact` or the pair
score, e.g. `setgrp "IMG_1234.ARW" cake-cutting member exact`.

### 2.2 Name the group

One `$GROUP` per cluster from what the pictures show — place plus moment,
e.g. `church-steps-noon`, `villa-toast`. Normalise with `slug()` and keep it
in column 1 bare: it becomes the folder name verbatim. On collision with
another cluster's slug — or with an existing `$POOL/$GROUP/` directory —
append `-2`, `-3`.

### 2.3 Crown the recommended

Pre-rank each group by numbers alone, cheapest first:

```bash
rank() {  # usage: rank <file>: pixels, sharpness proxy, bytes — larger is better
  px=$(jq -r --arg f "$1" '.[] | select(.FileName==$f) |
    ((.ImageWidth // 0) * (.ImageHeight // 0))' "$INVENTORY")
  sh=$(magick "$THUMBS/$1.thumb.png" -colorspace Gray \
    -morphology Convolve Laplacian:0 -format "%[standard-deviation]" info: \
    2>/dev/null || echo 0)
  sz=$(jq -r --arg f "$1" '.[] | select(.FileName==$f) | (.FileSize // 0)' \
    "$INVENTORY")
  echo "$px $sh $sz $1"
}
```

Then read the top three proxies inline — unless the 1.6 verdicts already
separate them — and crown the best-looking one with `setrec`, note one
short phrase (`eyes-open`, `best-framing`, `sharpest-smile`). Aesthetic
overrides numbers every time: the largest file with someone mid-blink loses
to the smaller one with eyes open. Exact-dupe groups need no vision: crown
the largest file.

When to crown nothing: some groups have no reasonable pick — group portraits
where virtues split across frames (eyes open here, genuine smiles there, no
frame with all of them), sets where every candidate shares the same
disqualifier (all mid-blink, all soft), or full ties vision and numbers both
refuse to break. A forced pick there is worse than none: it stamps one frame
as best on no grounds. Leave such a group members-only — never call `setrec`
for it — and record why in every member's note as `no-pick:<short-reason>`
(e.g. `no-pick:split-smiles`, `no-pick:all-soft`). `setrec` demotes the
group's previous pick, so a group mechanically holds at most one.

### 2.4 Gate — every asset must be placed

Phase 3 does not start until this prints `OK`:

```bash
todo=$(wc -l < "$WORK/todo.txt" | tr -d ' ')
rows=$(grep -cve '^[[:space:]]*$' -e '^#' "$CLUSTERS")
unrev=$(awk -F'\t' '$1=="?"' "$CLUSTERS" | wc -l | tr -d ' ')
multi=$(awk -F'\t' '$1!="?" && $3!="single" {print $1}' "$CLUSTERS" \
  | sort | uniq -c | awk '$1<2')
awk -F'\t' '$1!="?" && $3!="single" {print $1}' "$CLUSTERS" \
  | sort -u > "$WORK/groups.txt"
multirec=$(awk -F'\t' '$3=="recommended" {print $1}' "$CLUSTERS" \
  | sort | uniq -d)
nopick=$(while IFS= read -r g; do
    awk -F'\t' -v g="$g" '$1==g && $3=="recommended"' "$CLUSTERS" \
      | grep -q . || echo "$g"
  done < "$WORK/groups.txt" | wc -l | tr -d ' ')
mix=$(awk -F'\t' '$1!="?" && $1!="-" && $3!="single" {print $1 "\t" $2}' \
  "$CLUSTERS" | while IFS=$'\t' read -r g f; do
    if isvid "$f"; then echo "$g video"; else echo "$g still"; fi
  done | sort -u | cut -d' ' -f1 | uniq -d)
badslug=$(awk -F'\t' '$1!="?" && $1!="-" {print $1}' "$CLUSTERS" | sort -u \
  | awk 'length > 32 || $0 !~ /^[a-z0-9][a-z0-9-]*$/')
echo "todo $todo | rows $rows | unreviewed $unrev | singleton-groups $multi | groups-multi-pick [$multirec] | groups-no-pick $nopick | mixed-type [$mix] | bad-slug [$badslug]"
[ "$todo" = "$rows" ] && [ "$unrev" -eq 0 ] && [ -z "$multi" ] \
  && [ -z "$multirec" ] && [ -z "$mix" ] && [ -z "$badslug" ] && echo OK || echo "NOT READY"
```

Then show the user the group table with counts, the pick per group with its
one-phrase reason, the members-only groups with their `no-pick` reasons, the
singleton count, and anything in `$FAILED` — and wait for a yes.

---

## Phase 3 — Apply

### 3.1 The only step that moves

One `mv` per grouped asset, filenames taken from `$CLUSTERS`, folders created
here and nowhere else:

```bash
: > "$WORK/renamed.txt"
awk -F'\t' '$1!="?" && $3!="single" {print $1 "\t" $2 "\t" $3}' "$CLUSTERS" \
| while IFS=$'\t' read -r grp fname role; do
  mkdir -p "$POOL/$grp"
  if [ "$role" = "recommended" ]; then dest="$POOL/$grp/recommended-$fname";
  else dest="$POOL/$grp/$fname"; fi
  if [ -e "$dest" ]; then
    stem="${fname%.*}"; ext="${fname##*.}"
    if [ "$role" = "recommended" ]; then dest="$POOL/$grp/recommended-$stem-2.$ext";
    else dest="$POOL/$grp/$stem-2.$ext"; fi
  fi
  if mv -- "$POOL/$fname" "$dest"; then
    echo "$fname -> $dest" >> "$WORK/renamed.txt"
  else
    echo "mv failed: $fname" >> "$FAILED"
  fi
done
```

Singletons never move. Grouped files from earlier runs live in subfolders the
scan never sees, so nothing can be double-filed.

### 3.2 Report

```bash
top=$(wc -l < "$WORK/have.txt" | tr -d ' ')
ok=$(wc -l < "$WORK/renamed.txt" | tr -d ' ')
singles=$(awk -F'\t' '$3=="single"' "$CLUSTERS" | wc -l | tr -d ' ')
bad=$(grep -c '^mv failed:' "$FAILED" 2>/dev/null || true)
grouped=$(find "$POOL" -mindepth 2 -type f | wc -l | tr -d ' ')
echo "top-level $top | moved $ok | singles $singles | failed $bad | grouped-total $grouped"
[ $((ok + singles + bad)) -eq "$top" ] \
  || echo "MISMATCH: a top-level asset was never attempted"
find "$POOL" -mindepth 3 | head                       # must be empty: no nesting
find "$POOL" -mindepth 2 -name '*recommended*recommended*'  # must be empty
find "$POOL" -mindepth 2 -name 'recommended-*' | sed 's|.*/||' | sort
cat "$FAILED"
wc -l < "$WORK/dropped.tsv"                          # cross-type pairs dropped
```

Every `$POOL/$GROUP/` directory must hold ≥2 files and at most one
`recommended-*` file — groups with none are abstentions (2.3), listed with
their `no-pick` reasons. Only `mv failed:` lines count as failed assets —
every grouped file still sitting at the top level must have one. Other
`$FAILED` lines (`thumb`/`proxy`/`frame`) are step diagnostics: an asset
behind one is counted once, under `singles` with its note. Grouped files sit
one level down, outside `apto`'s top-level view — expected. `aduno` runs last.
Give the user the counts and every line of `$FAILED`, named. Then
`rm -rf "$WORK"`.
