import sublime
import os
from threading import Thread
import signal, subprocess
import json
from hashlib import sha1 

if int(sublime.version()) >= 3000:
    from .base_command import BaseCommand
else:
    from base_command import BaseCommand
    
class GulpCommand(BaseCommand):
    package_name = "Gulp"
    cache_file_name = ".sublime-gulp.cache"
    
    def work(self):
        self.set_instance_variables()
        self.list_gulp_files()

    def set_instance_variables(self):
        self.gulp_files = []
        self.env = Env(self.settings)

    def list_gulp_files(self):
        self.folders = []
        for folder_path in self.window.folders():
            self.folders.append(folder_path)
            self.append_to_gulp_files(folder_path)
        if len(self.gulp_files) > 0:
            self.choose_file()
        else:
            sublime.error_message("gulpfile.js or gulpfile.coffee not found!")

    def append_to_gulp_files(self, path):
        if os.path.exists(os.path.join(path, "gulpfile.js")):
            self.gulp_files.append(os.path.join(path, "gulpfile.js"))
        elif os.path.exists(os.path.join(path, "gulpfile.coffee")):
            self.gulp_files.append(os.path.join(path, "gulpfile.coffee"))

    def choose_file(self):
        if len(self.gulp_files) == 1:
            self.show_tasks_from_gulp_file(0)
        else:
            self.window.show_quick_panel(self.gulp_files, self.show_tasks_from_gulp_file)

    def show_tasks_from_gulp_file(self, file_index):
        if file_index > -1:
            self.working_dir = os.path.dirname(self.gulp_files[file_index])
            self.tasks = self.list_tasks()
            if self.tasks is not None:
                self.show_quick_panel(self.tasks, self.run_gulp_task)

    def list_tasks(self):
        try:
            self.callcount = 0
            json_result = self.fetch_json()
        except TypeError as e:
            sublime.error_message("SublimeGulp: JSON  cache (.sublime-gulp.cache) is malformed.\nCould not read available tasks\n")
        else:
            tasks = [[name, self.dependencies_text(task)] for name, task in json_result.items()]
            return sorted(tasks, key = lambda task: task)

    def dependencies_text(self, task):
        return "Dependencies: " + task['dependencies'] if task['dependencies'] else ""

    # Refactor
    def fetch_json(self):
        jsonfilename = os.path.join(self.working_dir, self.cache_file_name)
        gulpfile = os.path.join(self.working_dir, "gulpfile.js") # .coffee ?
        data = None

        if os.path.exists(jsonfilename):
            filesha1 = Security.hashfile(gulpfile)
            json_data = open(jsonfilename)

            try:
                data = json.load(json_data)
                if data[gulpfile]["sha1"] == filesha1:
                    return data[gulpfile]["tasks"]
            finally:
                json_data.close()

        self.callcount += 1

        if self.callcount == 1: 
            return self.write_to_cache()

        if data is None:
            raise TypeError("Could not write to cache gulpfile")

        raise TypeError("Sha1 from gulp cache ({0}) is not equal to calculated ({1})".format(data[gulpfile]["sha1"], filesha1))

    def write_to_cache(self):
        package_path = os.path.join(sublime.packages_path(), self.package_name)

        args = r'node "%s/write_tasks_to_cache.js"' % package_path # Test in ST2

        write_to_cache = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env.get_path_with_exec_args(), cwd=self.working_dir, shell=True)
        (stdout, stderr) = write_to_cache.communicate()

        if 127 == write_to_cache.returncode:
            sublime.error_message("\"node\" command not found.\nPlease be sure to have node installed and in your PATH.")
            return

        return self.fetch_json()

    def run_gulp_task(self, task_index):
        thread = Thread(target = self.__run__, args = (task_index, ))
        # Option to kill on timeout. Check thread.isAlive or fire on sublime.set_async_timeout(kill, timeout)
        thread.start()

    def __run__(self, task_index):
        if task_index > -1:
            task_name = self.tasks[task_index][0]
            cmd = r"gulp %s" % task_name

            process = CrossPlatformProcess(self).run(cmd)
            ProcessCache.add(process)
            self.show_output_panel("Running %s...\n" % task_name) # Just show the panel don't override the contents.
            self.show_process_output(process)

    def show_process_output(self, process):
        # Test in ST2!
        for line in process.stdout:
            self.append_to_output_view(str(line.rstrip().decode('utf-8')) + "\n") # Move viewport to the end
        process.terminate()
        # Remove from cache


class GulpKillCommand(BaseCommand):
    def run(self):
        ProcessCache.each(self.kill)
        ProcessCache.clear()

    def kill(self, process):
        CrossPlatformProcess.kill(process)
        self.display_message("All running tasks killed!") # Show in panel, make sure it exists

class CrossPlatformProcess():
    def __init__(self, command):
        self.path = command.env.get_path_with_exec_args()
        self.working_dir = command.working_dir

    def run(self, cmd):
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.path, cwd=self.working_dir, shell=True, preexec_fn=self._preexec_val())
        return process

    def _preexec_val(self):
        return os.setsid if sublime.platform() != "windows" else None

    @classmethod
    def kill(cls, process):
        if sublime.platform() == "windows":
            kill_process = subprocess.Popen(['taskkill', '/F', '/T', '/PID', str(process.pid)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            kill_process.communicate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                print("Process not found")

class ProcessCache():
    _procs = []

    @classmethod
    def add(cls, proc):
       cls._procs.append(proc)

    @classmethod
    def each(cls, fn):
        for proc in cls._procs:
            fn(proc)

    @classmethod
    def clear(cls):
        del cls._procs[:]

class Env():
    def __init__(self, settings):
        self.exec_args = settings.get('exec_args', False)

    def get_path(self):
        path = os.environ['PATH']
        if self.exec_args:
            path = exec_args.get('path', os.environ['PATH'])
        return str(path)

    def get_path_with_exec_args(self):
        env = os.environ.copy()
        if self.exec_args:
            path = str(exec_args.get('path', ''))
            if path:
                env['PATH'] = path
        return env

class Security():
    @classmethod
    def hashfile(cls, filename):
        with open(filename, mode='rb') as f:
            filehash = sha1()
            content = f.read();
            filehash.update(str("blob " + str(len(content)) + "\0").encode('UTF-8'))
            filehash.update(content)
            return filehash.hexdigest()
