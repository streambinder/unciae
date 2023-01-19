#!/usr/bin/env python

import argparse
import json
from datetime import datetime

import slugify
from imagededup.methods import PHash


def dups(target, threshold):
    fname = f'dups-{slugify.slugify(target)}-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
    method = PHash()
    encoding_map = method.encode_images(
        image_dir=target,
        recursive=True,
    )
    dups = method.find_duplicates(
        encoding_map=encoding_map,
        recursive=True,
        scores=True,
        max_distance_threshold=threshold,
    )
    rm = method.find_duplicates_to_remove(
        encoding_map=encoding_map,
        recursive=True,
        max_distance_threshold=threshold,
    )

    with open(fname, "w") as fd:
        json.dump({"dups": dups, "rm": rm}, fd)

    print(f"Results written at: {fname}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="dups",
        description="Scout for duplicate images in a target directory",
    )
    parser.add_argument(
        "dir",
        help="Target directory",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=int,
        default=5,
        help="Max distance threshold between assets",
    )

    args = parser.parse_args()
    dups(args.dir, args.threshold)
