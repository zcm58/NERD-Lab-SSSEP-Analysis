# Install on Windows

Do this once per computer. You need an internet connection.

1. **Install Python 3.11.** Open the official
   [Python 3.11.9 download page](https://www.python.org/downloads/release/python-3119/).
   Under **Files**, choose **Windows installer (64-bit)**. Run it and select
   **Add python.exe to PATH** if shown. Use Python 3.11 because the task's
   PsychoPy version does not support Python 3.13.

2. **Install PyCharm.** [Download PyCharm](https://www.jetbrains.com/pycharm/download/)
   and run its installer. The free version is sufficient.

3. **Get the project.** On the
   [repository page](https://github.com/zcm58/NERD-Lab-SSSEP-Analysis), select
   **Code > Download ZIP**, then extract it. If the page is unavailable, ask
   the lab for access.

4. **Open the project.** In PyCharm, select **Open** and choose the extracted
   folder containing `README.md`.

5. **Install the libraries.** Open PyCharm's **Terminal** in the project folder
   and run this one command. It creates `.venv`, installs the pinned PsychoPy
   version, and checks the installation.

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
   ```

6. **Select the environment.** If PyCharm asks for an interpreter, choose
   `.venv\Scripts\python.exe` inside the project.

7. **Check the launcher.** Right-click `main.py` and select **Run**. The task,
   recording-analysis, and saved-FFT plotting tabs should open.

[User guide](user-guide.md) | [Help](troubleshooting.md) | [Home](../README.md)
