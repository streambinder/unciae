#!/usr/bin/env python3

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
                    raise RuntimeError(f"{mandatory_token} key is mandatory for a task object")
            for recommended_token in ["retention"]:
                if recommended_token not in t or t[recommended_token] is None:
                    print(
                        f"Task for {t['repository']} has not {recommended_token} token.",
                        file=sys.stderr,
                    )
            path_checks = ["repository", "path"]
            path_checks += ["prespawn"] if "prespawn" in t else []
            path_checks += ["postspawn"] if "postspawn" in t else []
            for path_entry in path_checks:
                if not os.path.exists(t[path_entry]):
                    raise RuntimeError(f"{path_entry} path {t[path_entry]} does not exist")

    def __wait(self):
        for thread in self.__threads:
            thread.join()

    def __t_print(self, payload, file=sys.stdout):
        with self.__mutex:
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode("utf-8")
            print(payload, file=file)

    def __process(self, task):
        if "prespawn" in task:
            try:
                self.__t_print(f"Running pre-hook {task['prespawn']}...")
                subprocess.run(task["prespawn"], shell=True, check=True)
            except subprocess.CalledProcessError:
                self.__t_print(
                    f"Pre-task for {task['repository']} exited abnormally. Breaking up backup.",
                    file=sys.stderr,
                )
                return

        self.__t_print(f"Spawning {task['path']} directory restic backup")
        regexes = []
        if "regexes" in task:
            for regex in task["regexes"]:
                regexes += ["--iexclude", regex]
        with subprocess.Popen(["echo", task["password"]], stdout=subprocess.PIPE) as pipe_auth:
            with subprocess.Popen(
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
            ) as pipe_restic:
                pipe_out, pipe_err = pipe_restic.communicate()
                if pipe_err is not None:
                    self.__t_print(
                        f"Unable to backup {task['respository']} repository: {pipe_err}",
                        file=sys.stderr,
                    )
                    return
                self.__t_print(pipe_out)

        if "postspawn" in task:
            try:
                self.__t_print(f"Running post-hook {task['postspawn']}...")
                subprocess.run(task["postspawn"], shell=True, check=True)
            except subprocess.CalledProcessError:
                self.__t_print(
                    f"Post-task for {task['repository']} exited abnormally",
                    file=sys.stderr,
                )

        if "retention" in task:
            self.__t_print(f"Enforcing {task['retention']} retention...")
            with subprocess.Popen(["echo", task["password"]], stdout=subprocess.PIPE) as pipe_auth:
                with subprocess.Popen(
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
                ) as pipe_restic:
                    pipe_out, pipe_err = pipe_restic.communicate()
                    if pipe_err is not None:
                        self.__t_print(
                            f"Unable to apply retention on {task['respository']} repository: " + pipe_err,
                            file=sys.stderr,
                        )
                        return
                    self.__t_print(pipe_out)

        self.__t_print(f"Repository {task['repository']} updated")

    def run(self):
        for t in self.tasks:
            thread = threading.Thread(target=self.__process, args=[t])
            self.__threads.append(thread)
            thread.start()
        self.__wait()


if __name__ == "__main__":
    os.chdir(os.path.dirname(__file__))

    CFG_PATH = "config.yml"
    if len(sys.argv) > 1:
        CFG_PATH = sys.argv[1]

    try:
        with open(CFG_PATH, "r", encoding="utf-8") as yml_stream:
            Restup(yaml.safe_load(yml_stream)).run()
    except OSError as e:
        print(e, file=sys.stderr)
