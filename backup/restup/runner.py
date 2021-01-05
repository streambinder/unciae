#!/usr/bin/env python3

import collections
import os
import subprocess
import sys
import threading

import yaml


class Restup:
    def __init__(self, cfg):
        self.tasks = []
        self.__threads = []
        self.__mutex = threading.Lock()
        self.__parse_config(cfg)
        self.__validate_config()

    def __str__(self):
        return str(vars(self))

    def __parse_config(self, cfg):
        if "tasks" in cfg:
            self.tasks = cfg["tasks"]

    def __validate_config(self):
        for t in self.tasks:
            for mandatory_token in ["repository", "password", "path"]:
                if mandatory_token not in t or t[mandatory_token] is None:
                    raise Exception(
                        "{} key is mandatory for a task object".format(
                            mandatory_token)
                    )
            for recommended_token in ["retention"]:
                if recommended_token not in t or t[recommended_token] is None:
                    print(
                        "Task for {} has not {} token: it's highly recommended.".format(
                            t["repository"], recommended_token
                        ),
                        file=sys.stderr,
                    )
            path_checks = ["repository", "path"]
            path_checks += ["prespawn"] if "prespawn" in t else []
            path_checks += ["postspawn"] if "postspawn" in t else []
            for path_entry in path_checks:
                if not os.path.exists(t[path_entry]):
                    raise Exception(
                        "{} path {} does not exist".format(path_entry, t[path_entry])
                    )

    def __wait(self):
        for thread in self.__threads:
            thread.join()

    def __t_print(self, payload, file=sys.stdout):
        try:
            self.__mutex.acquire()
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            print(payload)
        finally:
            self.__mutex.release()

    def __process(self, task):
        if "prespawn" in task:
            try:
                self.__t_print("Running pre-hook {}...".format(task["prespawn"]))
                subprocess.run(task["prespawn"], shell=True, check=True)
            except subprocess.CalledProcessError:
                self.__t_print(
                    "Pre-task for {} exited abnormally. Breaking up backup.".format(
                        task["repository"]
                    ),
                    file=sys.stderr,
                )
                return

        self.__t_print("Spawning {} directory restic backup".format(task["path"]))
        regexes = []
        if "regexes" in task:
            for regex in task["regexes"]:
                regexes += ["--iexclude", regex]
        pipe_auth = subprocess.Popen(
            ["echo", "{}".format(task["password"])], stdout=subprocess.PIPE
        )
        pipe_restic = subprocess.Popen(
            [
                "restic",
                "-r",
                task["repository"],
                "backup",
                task["path"],
                "--exclude-caches",
            ]
            + regexes,
            stdin=pipe_auth.stdout,
            stdout=subprocess.PIPE,
        )
        pipe_auth.stdout.close()
        pipe_out, pipe_err = pipe_restic.communicate()
        if pipe_err is not None:
            self.__t_print(
                "Unable to backup {} repository: {}".format(
                    task["respository"], str(pipe_err)
                ),
                file=sys.stderr,
            )
            return
        self.__t_print(pipe_out)

        if "postspawn" in task:
            try:
                self.__t_print("Running post-hook {}...".format(task["postspawn"]))
                subprocess.run(task["postspawn"], shell=True, check=True)
            except subprocess.CalledProcessError:
                self.__t_print(
                    "Post-task for {} exited abnormally".format(task["repository"]),
                    file=sys.stderr,
                )

        if "retention" in task:
            self.__t_print("Enforcing {} retention...".format(task["retention"]))
            pipe_auth = subprocess.Popen(
                ["echo", "{}".format(task["password"])], stdout=subprocess.PIPE
            )
            pipe_restic = subprocess.Popen(
                [
                    "restic",
                    "-r",
                    task["repository"],
                    "forget",
                    "--prune",
                    "--keep-within",
                    task["retention"],
                ],
                stdin=pipe_auth.stdout,
                stdout=subprocess.PIPE,
            )
            pipe_auth.stdout.close()
            pipe_out, pipe_err = pipe_restic.communicate()
            if pipe_err is not None:
                self.__t_print(
                    "Unable to apply retention on {} repository: {}".format(
                        task["respository"], str(pipe_err)
                    ),
                    file=sys.stderr,
                )
                return
            self.__t_print(pipe_out)

        self.__t_print("Repository {} updated".format(task["repository"]))

    def run(self):
        for t in self.tasks:
            thread = threading.Thread(target=self.__process, args=[t])
            self.__threads.append(thread)
            thread.start()
        self.__wait()


if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))

    cfg_path = "config.yml"
    if len(sys.argv) > 1:
        cfg_path = sys.argv[1]

    try:
        with open(cfg_path, "r") as yml_stream:
            Restup(yaml.safe_load(yml_stream)).run()
    except Exception as e:
        print(e, file=sys.stderr)
