---
name: pono
description: >-
  Reconstruct where media assets were shot from EXIF GPS anchors, visual analysis and user-supplied coordinates, then write it with pono
---

# pono

Given a folder of media, work out where each asset was shot and write it:
`pono` sets GPS on every file that lacks it. A single file is a pool of one.

This skill does **location only**. Capture time and naming are the `apto`
skill. They
are independent and can run in either order: `pono` writes tags without
renaming, and those tags survive `apto`'s rename.

Run the commands here as they are written. They are not sketches.

## Rules

1. `exiftool` **reads only**. `pono` writes GPS. `tundo` repairs an asset `pono`
   could not write at all. `magick`/`ffmpeg` build proxies. Nothing else touches
   the pool. In particular you never run `exiftool -Tag=…` or `exiftool -all=`
   on an asset by hand: the second erases every tag the file has, and neither
   passes `-overwrite_original`, so both litter the pool with `<name>_original`
   backups. Rebuilding a damaged metadata block is `tundo`'s job, not yours.
2. Nothing under `$POOL` is ever deleted, moved, renamed or copied by you. Every
   `rm` you write spells out a path under `$WORK/` literally. Never hand `rm` a
   variable that has, anywhere in its life, held the path of a source file.
3. Images are looked at only through `view`, only as proxies. Never
   `read` an image: it makes every later request multimodal and uncacheable.
4. Read metadata once into `$INVENTORY`. Append every decision to `$ASSIGNMENTS`
   when you make it. Never retype a table you have already written.
5. Coordinates the user gives are **absolute**. Use their digits exactly. Never
   round them, never swap in a value derived from the files, and never weigh
   them against EXIF GPS or against the place name `pono -d` prints back — that
   is not your call, and reasoning about it wastes the run.
6. **Existing EXIF GPS is left alone.** A file that already carries coordinates
   is an anchor, not a target. `pono` only fills the gaps.
7. Everything is best effort, and **one `pono` command per venue**. If it
   fails, you are done with those assets: append the venue to `$FAILED` and
   move on. Do not retry it, do not fall back to per-file calls, do not reach
   for `exiftool`. A named failure is a finished result.
8. The **only** exception to 7 is the repair pass in 3.2, and it is bounded: one
   `tundo` over the assets a venue is still missing, then one final `pono` for
   that venue. By then those files' metadata blocks have been rebuilt, so the
   last call is aimed at different files, not a retry of the same ones. A venue
   still short afterwards is finished — it stays in `$FAILED`.

## Setup

```bash
POOL="<absolute path to pool>"   # absolute, never "." — a ./ prefix
                                 # poisons every later filename comparison
WORK="${TMPDIR:-/tmp}/pono-skill/$(basename "$POOL")"  # never inside $POOL
PROXIES="$WORK/proxies"; FRAMES="$WORK/frames"
INVENTORY="$WORK/inventory.json"
ASSIGNMENTS="$WORK/assignments.tsv"
VENUES="$WORK/venues.tsv"
VISION="$WORK/vision.txt"
FAILED="$WORK/failed.txt"
rm -rf "$WORK/proxies" "$WORK/frames"        # derived, always rebuilt
mkdir -p "$PROXIES" "$FRAMES"; : > "$FAILED"; : > "$WORK/proxy_list.txt"
```

---

## Phase 1 — Collect

### 1.1 Ask the user

Two questions, then stop and wait:

1. **Which places?** One line per venue: a short name, and either an address or
   `lat,lon`. Give me your coordinates if you have them — I will use them
   exactly as typed.
2. **Anything I should know about movement?** Which venue came first, whether
   anyone travelled between them, whether some assets were shot elsewhere.

Write the answers to `$VENUES`, keeping the user's digits verbatim:

```bash
venue() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$VENUES"; }

venue church 43.1066048002844 12.35181938629971
venue villa  43.15299637380922 12.555755231796168
```

The columns are `<venue-name>` `<lat>` `<lon>`.

### 1.2 Inventory (run as-is)

```bash
EXT=(); for e in jpg jpeg png webp heic dng arw nef mp4 mov m4v avi 3gp wmv; do
  EXT+=(-ext "$e")
done

exiftool -q -n -json -api QuickTimeUTC=1 "${EXT[@]}" \
  -FileName -DateTimeOriginal -CreateDate \
  -GPSLatitude -GPSLongitude -Model -Make -Software \
  "$POOL" > "$INVENTORY"

jq 'length' "$INVENTORY"                                    # assets
jq '[.[]|select(.GPSLatitude)]|length' "$INVENTORY"         # already anchored
jq -r '.[]|select(.GPSLatitude==null)|.FileName' "$INVENTORY"   # need pono
```

`-n` gives signed decimals, so GPS never needs parsing — there is never a reason
to pick apart `43 deg 6' 18.30" N` by hand. Absent tags are missing keys.

Now seed `$ASSIGNMENTS` from it. Every asset gets a row, `?` for the venue and
`yes`/`no` already filled in from whether it carries GPS:

```bash
jq -r '.[] | "\(.FileName)\t?\t\(if .GPSLatitude then "yes" else "no" end)"' \
  "$INVENTORY" > "$ASSIGNMENTS"
wc -l < "$ASSIGNMENTS"
```

You never type a filename, and column 3 is derived rather than judged.

### 1.3 Anchors from the files themselves (run as-is)

Assets that already carry GPS tell you where the venues actually were. Cluster
them on **both** axes — latitude alone merges places that share a parallel.

```bash
jq -r '.[] | select(.GPSLatitude)
       | "\(.GPSLatitude*1000|round/1000),\(.GPSLongitude*1000|round/1000)"' \
  "$INVENTORY" | sort | uniq -c | sort -rn
```

Each group of any size is a real place someone stood. Match them to the venues
in `$VENUES` by count and by what the photos show. Rounding here is for grouping
only — it never reaches `pono`, which gets the user's digits.

If a group matches no venue the user named, ask about it rather than guessing.

### 1.4 Proxies (run as-is)

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

Those counts must match. `-auto-orient` is mandatory: the vision model never
sees EXIF, so an unrotated proxy is read sideways.

### 1.5 Vision

`view` is the only way you look at anything. Batch per venue
hypothesis; pass the frames of one video together and treat them as one asset.

```bash
cat "$WORK/proxy_list.txt"          # one line per still, current assets only
find "$FRAMES" -type f | sort       # video frames, three per clip
```

```text
view(paths: ["$PROXIES/IMG_1.jpg.jpg", "$PROXIES/IMG_2.dng.jpg", ...])
```

Ask about place, not time: indoor or outdoor, the kind of room or grounds,
architecture, signage, furniture, vegetation, whether it looks like the same
building as another batch. **Do not try to name the city, street or landmark** —
you are matching assets to venues the user already named, not identifying them.

Append each result to `$VISION` keyed by proxy path and read it back later.
A proxy is `<original filename>.jpg`, so strip one trailing `.jpg`.

---

## Phase 2 — Analyse

### 2.1 Put every asset at exactly one venue

- An asset with EXIF GPS is already placed. Record its venue and leave the tags
  alone — `pono` will not be run on it.
- An asset without GPS is placed by what it shows, matched against the anchor
  groups from 1.3 and the descriptions of assets that do have GPS.
- Assets shot minutes apart on the same device are almost always at the same
  venue. Use that, but let the picture win when it disagrees.
- There is **no unknown bucket**. Every asset goes to one of the venues in
  `$VENUES`. If something genuinely was shot elsewhere, ask the user for that
  venue and add a row — do not invent `unknown`, `other` or `misc`.

### 2.2 Write the assignment

The rows already exist from 1.2 with column 3 filled in. You only set the venue,
with `setvenue`, which **refuses a filename that is not already in the file** so
a mistyped name is an immediate error rather than a duplicate row.

```bash
setvenue() {
  grep -q "^$1$(printf '\t')" "$ASSIGNMENTS" || { echo "NO SUCH ASSET: $1"; return 1; }
  awk -F'\t' -v f="$1" -v v="$2" 'BEGIN{OFS="\t"} $1==f {$2=v} {print}' \
    "$ASSIGNMENTS" > "$WORK/a.tmp" && mv "$WORK/a.tmp" "$ASSIGNMENTS"
}

setvenue "IMG_1234.jpg" church
setvenue "IMG_1234.jpg" villa      # changed your mind, same call
```

The columns are `<filename>` `<venue-name>` `<yes|no>`. The venue name must
match a row in `$VENUES` exactly; `yes` in column 3 means the asset already
carries GPS and 3.1 skips it. Rows keep their order and stay unique, so there is
never anything to dedupe.

To set a whole group at once, drive `setvenue` from a list of filenames you
already have — from the 1.3 anchor clustering or from `jq` — never retyped.

### 2.3 Gate — every asset must be placed

Phase 3 does not start until this prints `OK`:

```bash
assets=$(find "$POOL" -maxdepth 1 -type f -not -name '.*' ! -name '*_original' | wc -l | tr -d ' ')
rows=$(grep -cve '^[[:space:]]*$' -e '^#' "$ASSIGNMENTS")
bad=$(awk -F'\t' 'NF<3 || $2=="" || $2=="?" || ($3!="yes" && $3!="no")' "$ASSIGNMENTS" | wc -l | tr -d ' ')
unknown=$(awk -F'\t' 'NR==FNR{v[$1];next} !($2 in v)' "$VENUES" "$ASSIGNMENTS" | wc -l | tr -d ' ')
echo "assets $assets | rows $rows | unreviewed-or-malformed $bad | venue not in \$VENUES $unknown"
[ "$assets" = "$rows" ] && [ "$bad" -eq 0 ] && [ "$unknown" -eq 0 ] && echo OK || echo "NOT READY"

find "$POOL" -maxdepth 1 -type f -not -name '.*' ! -name '*_original' \
  | sed 's|.*/||' | sort > "$WORK/have.txt"
cut -f1 "$ASSIGNMENTS" | sort > "$WORK/placed.txt"
comm -3 "$WORK/have.txt" "$WORK/placed.txt"       # left: unplaced, right: extra
```

Then show the user the venue table with counts, and wait for a yes.

---

## Phase 3 — Apply

### 3.1 GPS — one command per venue

One `pono` call per venue, every path for that venue on it. `xargs -I{}` or
`-n 1` runs it once per file, which buys nothing and — on the address form —
gets you rate-limited.

```bash
while IFS=$'\t' read -r VENUE LAT LON; do
  [ -z "$VENUE" ] && continue

  # absolute paths, and only the assets that lack GPS. `cut -f1` gives bare
  # names; pono resolves them against $PWD, prints "No such file or directory"
  # per path — and still exits 0.
  awk -F'\t' -v v="$VENUE" -v d="$POOL" '$2==v && $3=="no" {print d "/" $1}' \
    "$ASSIGNMENTS" > "$WORK/loc.txt"
  [ -s "$WORK/loc.txt" ] || continue

  # count files that HAVE gps; never match on the value, exiftool stores it
  # back at a different precision than the one you passed in
  withgps() { exiftool -q -n -T -GPSLatitude "$POOL" 2>/dev/null | grep -cv '^-$'; }
  before=$(withgps)
  tr '\n' '\0' < "$WORK/loc.txt" | xargs -0 pono -a "@$LAT,$LON"
  echo "$VENUE: wanted $(wc -l < "$WORK/loc.txt" | tr -d ' '), written $(( $(withgps) - before ))"
  [ "$(withgps)" -gt "$before" ] || echo "pono wrote nothing for $VENUE" >> "$FAILED"
done < "$VENUES"
```

`@` is mandatory: with it `pono` writes your numbers and makes no network call
at all, and without it the argument is geocoded as a search string and you get
some nearby venue instead. **Check the counts.** `pono` exits 0 when every path
it was handed was missing, so a silent no-op over 200 files looks exactly like
success. Only the address form touches the network — a `jq: parse error` there
means Nominatim is rate-limiting, so record it and move on.

### 3.2 Repair — what a short count actually means

A venue that wrote fewer files than it wanted has usually **not** skipped one and
carried on. `pono` stops at the first asset it cannot write and never reaches the
remaining paths in that call, so everything after the damaged file is still
untagged. One bad asset early in a venue's list can cost you the whole venue.

The cause is a metadata block exiftool refuses to rewrite, the same one that
stops `apto`:

```text
Error: Error reading OtherImageStart data in IFD0 - <path>
```

`-m` does not cover it — that error is fatal, not minor. `tundo` rebuilds the
block off the file's own tags, which drops the dangling pointer.

```bash
withgps() { exiftool -q -n -T -GPSLatitude "$POOL" 2>/dev/null | grep -cv '^-$'; }

while IFS=$'\t' read -r VENUE LAT LON; do
  [ -z "$VENUE" ] && continue

  # what this venue is still missing, re-read from the files rather than assumed from
  # 3.1's counts: which paths a stopped call had already reached is not knowable
  : > "$WORK/still.txt"
  while IFS= read -r p; do
    [ "$(exiftool -q -n -T -GPSLatitude "$p" 2>/dev/null)" = "-" ] &&
      echo "$p" >> "$WORK/still.txt"
  done < <(awk -F'\t' -v v="$VENUE" -v d="$POOL" \
    '$2==v && $3=="no" {print d "/" $1}' "$ASSIGNMENTS")
  [ -s "$WORK/still.txt" ] || continue

  # tundo probes before touching anything, so the assets that were merely queued behind
  # the damaged one come back "already writable" and are passed through untouched
  tr '\n' '\0' < "$WORK/still.txt" | xargs -0 tundo || true
  before=$(withgps)
  tr '\n' '\0' < "$WORK/still.txt" | xargs -0 pono -a "@$LAT,$LON"
  written=$(( $(withgps) - before ))
  echo "$VENUE: was missing $(wc -l < "$WORK/still.txt" | tr -d ' '), written $written"
  [ "$written" -gt 0 ] || echo "pono still wrote nothing for $VENUE" >> "$FAILED"
done < "$VENUES"
```

This pass runs **once**. A venue still short afterwards is a finished result — do
not reach for `tundo --force`, and do not go round again.

`tundo`'s rebuild is lossy on files that did not need it: the embedded thumbnail,
the MPF secondary images and any vendor HDR gain map do not survive the
copy-back. That is why it is pointed only at the assets a venue is still missing,
and why you never run it across `$POOL` as a precaution.

### 3.3 Report

```bash
total=$(find "$POOL" -maxdepth 1 -type f -not -name '.*' ! -name '*_original' | wc -l | tr -d ' ')
have=$(exiftool -q -n -T -GPSLatitude "$POOL" 2>/dev/null | grep -cv '^-$')
echo "assets: $total | with GPS: $have"

exiftool -q -GPSLatitude -GPSLongitude -n -T "$POOL" | sort | uniq -c | sort -rn
find "$POOL" -maxdepth 1 -name '*_original'     # must be empty: a tool was bypassed
cat "$FAILED"
```

One position per venue, plus whatever the anchored assets already carried. More
positions than that means a run wrote coordinates it derived instead of the
user's — find them and rewrite.

Every asset without GPS at the end must appear in `$FAILED`, and only because
`pono` refused it after 3.2 had its one attempt at repairing it. "No GPS in the
original" is not a reason — that is the input, not an outcome. "Damaged
metadata" is not one either: 3.2 is where that gets settled, and a run that
reports it without having run `tundo` skipped a step. Give the user the counts
and every line of `$FAILED`, named. Then `rm -rf "$WORK"`.
