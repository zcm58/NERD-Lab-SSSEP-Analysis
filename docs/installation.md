# Install on Windows

Do this once per computer. You need an internet connection for installation.

1. **Install Python.** Open the [Python 3.13.5 release page](https://www.python.org/downloads/release/python-3135/).
   Under **Files**, choose **Windows installer (64-bit)**. Run the downloaded
   file, select **Add python.exe to PATH** if shown, then **Install Now**.
   Use **Python 3.13** (tested: 3.13.5), not Python 3.14 or later.

2. **Install PyCharm.** [Download PyCharm](https://www.jetbrains.com/pycharm/download/)
   for Windows and run its installer. Its
   [free core features](https://www.jetbrains.com/help/pycharm/quick-start-guide.html)
   are sufficient; no paid subscription is needed.

3. **Get the project.** On the [repository page](https://github.com/zcm58/NERD-Lab-SSSEP-Analysis),
   select **Code > Download ZIP**. If the page is unavailable, ask the lab for
   access. In Windows File Explorer, right-click the
   downloaded ZIP and select **Extract All**. If you already cloned this
   repository, use that existing folder instead.

4. **Open the project.** In PyCharm, select **Open** (or **File > Open**).
   Choose the extracted folder containing `README.md`, `requirements.txt`, and
   `sssep_bdf_batch_processor.py`. Wait for the project to load.

5. **[Create the project environment](https://www.jetbrains.com/help/pycharm/creating-virtual-environment.html).**
   Press **Ctrl+Alt+S**, then select **Python > Interpreter > Add Interpreter >
   Add Local Interpreter**. Choose a new **Virtualenv** environment. Set its
   base interpreter to **Python 3.13** and its location to `.venv` inside this
   project folder. Leave **Inherit packages from base interpreter** unchecked.
   Click **OK**.

6. **Install the libraries.** In PyCharm's Project pane, right-click
   `requirements.txt` and select **Open in > Terminal**. This opens the terminal
   in the project folder. Run this command there:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
   ```

   Wait until it finishes without errors. Environment activation is unnecessary.

7. **Check the launcher.** Right-click `sssep_bdf_batch_processor.py` in the
   Project pane and select **Run 'sssep_bdf_batch_processor'**. The folder-selection
   window should open. Close it; setup is complete.

[User guide](user-guide.md) | [Help](troubleshooting.md) | [Home](../README.md)
