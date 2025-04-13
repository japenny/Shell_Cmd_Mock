#! /usr/bin/env python3
"""
A simple shell implementation that supports basic command execution,
pipes, I/O redirection, and background processes.
"""

import os, sys, re


class Shell:
    """A basic shell that parses and executes commands with support for
    piping, I/O redirection and background processes."""

    def __init__(self):
        """Initialize shell with built-in commands."""
        self.std_cmds = {
            "cd": self.cd,
            "exit": self.exit,
            "pwd": self.pwd,
        }

    def parser(self, cmds):
        """
        Parse command string into structured command objects.

        Args:
            cmds: String containing command(s) to parse

        Returns:
            List of command dictionaries with cmd, args, input/output redirections,
            and background process flags. Returns False on syntax error.
        """
        pipe_commands = cmds.split('|')
        commands = []
        n_cmds, i = len(pipe_commands), 0

        while i < n_cmds:
            cmd = pipe_commands[i]
            cmd = cmd.strip()

            # Check for background process
            background = False
            if cmd.endswith('&'):
                if i < n_cmds - 1:
                    os.write(2, "-bash: syntax error near unexpected token `|'\n".encode())
                    return False
                else:
                    background = True
                    cmd = cmd[:-1].strip()

            # Parse input and output redirections with regex
            inp_match = re.search(r'<\s*(\S+)', cmd)
            out_match = re.search(r'>\s*(\S+)', cmd)

            inp = inp_match.group(1) if inp_match else None
            out = out_match.group(1) if out_match else None

            # Remove redirection parts from the command
            cmd = re.sub(r'[<>]\s*\S+', '', cmd).strip()

            # Split command and arguments
            parts = cmd.split()
            if parts:
                commands.append({
                    'cmd': parts[0],
                    'args': parts,
                    'input': inp,
                    'output': out,
                    'background': background
                })
            i += 1
        return commands

    def pwd(self, args):
        """Print current working directory."""
        os.write(1, os.getcwd().encode())

    def cd(self, args):
        """
        Change current directory.

        Args:
            args: Command arguments where args[1] is the target directory
        """
        try:
            if len(args) == 1:
                os.chdir(os.path.expanduser('~'))
            elif args[1] == '~':
                os.chdir(os.path.expanduser('~'))
            elif args[1] == '/':
                os.chdir('/')
            else:
                os.chdir(args[1])
        except FileNotFoundError:
            print(f"cd {args[1]}: No such file or directory")
        except PermissionError:
            print(f"cd {args[1]}: Permission denied")

    def exit(self, args):
        """Exit the shell."""
        sys.exit(0)

    def find_executable(self, cmd):
        """
        Locate executable in PATH or by absolute path.

        Args:
            cmd: Command dictionary containing command name

        Returns:
            Full path to executable or None if not found
        """
        cmd = cmd['cmd']
        if os.path.isabs(cmd) and os.access(cmd, os.X_OK):
            return cmd

        # Search executable in PATH
        paths = re.split(":", os.environ['PATH'])
        for path in paths:
            exe = os.path.join(path, cmd)
            if os.access(exe, os.X_OK):
                return exe

        return None

    def execute(self, exe, cmd):
        """
        Execute a command using execve.

        Args:
            exe: Full path to executable
            cmd: Command dictionary with arguments
        """
        if exe is None:
            os.write(2, f"{cmd['cmd']}: command not found\n".encode())
            sys.exit(1)

        try:
            os.execve(exe, cmd['args'], os.environ)
        except FileNotFoundError:
            os.write(2, f"Failed to execute: {exe}".encode())
            sys.exit(1)

    def redirect(self, cmd):
        """
        Set up input/output redirections for a command.

        Args:
            cmd: Command dictionary with input/output redirection paths
        """
        if cmd['input']:
            os.close(0)
            os.open(cmd['input'], os.O_RDONLY)
            os.set_inheritable(0, True)

        if cmd['output']:
            os.close(1)
            os.open(cmd['output'], os.O_CREAT | os.O_WRONLY)
            os.set_inheritable(1, True)

    def run_cmds(self, cmds):
        """
        Execute commands, handling pipes and background processes.

        Args:
            cmds: List of command dictionaries to execute
        """
        cmd_0, cmd_1 = cmds if len(cmds) != 1 else (cmds[0], None)
        is_background = cmds[-1].get('background')

        # Create pipe if needed
        pr, pw = None, None
        if cmd_1:
            pr, pw = os.pipe()
            for f in (pr, pw):
                os.set_inheritable(f, True)

        pid = os.getpid()
        rc = os.fork()

        if rc < 0:
            os.write(2, ("Fork failed, returning %d\n" % rc).encode())
            sys.exit(1)

        elif rc == 0:  # Child process
            exe = self.find_executable(cmd_0)
            self.redirect(cmd_0)

            # Set up pipe output if needed
            if cmd_1:
                os.close(pr)  # Close unused read end
                os.dup2(pw, 1)  # Redirect stdout to write end of pipe
                os.close(pw)  # Close original write end

            self.execute(exe, cmd_0)

        else:  # Parent process
            if cmd_1:
                os.close(pw)  # Close unused write end
                child1_status = os.waitpid(rc, 0)

                if child1_status[1] != 0:
                    os.write(2,
                             f"Parent: Child 1 {child1_status[0]} "
                             f"terminated with exit code {child1_status[1]}\n".encode())

                # Fork again for the second command in the pipe
                rc2 = os.fork()

                if rc2 < 0:
                    os.write(2, ("Second fork failed, returning %d\n" % rc).encode())
                    sys.exit(1)
                elif rc2 == 0:  # Second child
                    exe2 = self.find_executable(cmd_1)
                    self.redirect(cmd_1)

                    os.dup2(pr, 0)  # Redirect stdin to the read end of the pipe
                    os.close(pr)  # Close original read end

                    self.execute(exe2, cmd_1)
                else:  # Parent again
                    os.close(pr)

                    if is_background:
                        os.write(2, f"Background process (pipe)\n".encode())
                        return

                    # Wait for second child to complete
                    child2_status = os.waitpid(rc2, 0)
                    if child2_status[1] != 0:
                        os.write(1,
                                 f"Parent: Child 2 {child2_status[0]} "
                                 f"terminated with exit code {child2_status[1]}\n".encode())

            else:  # Single command (no pipe)
                if is_background:
                    os.write(2, f"Background process (single)\n".encode())
                    return

                # Wait for child to complete
                childPidCode = os.wait()
                if childPidCode[1] != 0:
                    os.write(1, f"Parent: Child {childPidCode[0]} terminated "
                                f"with exit code {childPidCode[1]}\n".encode())

    def run_shell(self):
        """Main shell loop that prompts for and processes user commands."""
        ps1 = os.getenv("PS1", "$ ")

        while True:
            try:
                os.write(1, ps1.encode())
                user_in = sys.stdin.readline().strip()

                if user_in.startswith("exit"):
                    self.exit('')

                if len(user_in) == 0:
                    print("")
                    continue

                # Parse and execute commands
                parsed_cmds = self.parser(user_in)
                if not parsed_cmds:
                    print("no commands")
                    continue

                self.run_cmds(parsed_cmds)

            except EOFError:
                print("\nEOFError. Exiting shell.")
                break

            except SystemExit:
                print("Exiting shell.")
                break


if __name__ == '__main__':
    shell = Shell()
    shell.run_shell()