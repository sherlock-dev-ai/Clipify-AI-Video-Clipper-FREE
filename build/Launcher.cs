using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;

namespace ClipifyAI
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string appPy = Path.Combine(baseDir, "app.py");
            string logFile = Path.Combine(baseDir, "launcher.log");
            string pyLog = Path.Combine(baseDir, "python_live.log");

            // 1. Check if server is already running and healthy on port 5000
            bool alreadyRunning = false;
            try
            {
                var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:5000/api/health");
                req.Timeout = 1200;
                using (var resp = (HttpWebResponse)req.GetResponse())
                {
                    if (resp.StatusCode == HttpStatusCode.OK)
                    {
                        alreadyRunning = true;
                    }
                }
            }
            catch { }

            if (alreadyRunning)
            {
                OpenAppWindow("http://127.0.0.1:5000/");
                return;
            }

            // 2. Locate Python runtime
            string pythonExe = Path.Combine(baseDir, "runtime", "Scripts", "python.exe");
            if (!File.Exists(pythonExe))
            {
                pythonExe = Path.Combine(baseDir, "runtime", "Scripts", "pythonw.exe");
            }
            if (!File.Exists(pythonExe))
            {
                pythonExe = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");
            }
            if (!File.Exists(pythonExe))
            {
                pythonExe = "python.exe";
            }

            // 3. Configure environment and launch
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonExe;
            psi.Arguments = "-u \"" + appPy + "\"";
            psi.WorkingDirectory = baseDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;

            // Environment
            string runtimeDir = Path.Combine(baseDir, "runtime");
            string ffmpegDir = Path.Combine(baseDir, "tools", "ffmpeg", "ffmpeg-9.0.1-essentials_build", "bin");
            string currentPath = Environment.GetEnvironmentVariable("PATH") ?? "";
            psi.EnvironmentVariables["PATH"] = Path.Combine(runtimeDir, "Scripts") + ";" + runtimeDir + ";" + ffmpegDir + ";" + currentPath;
            psi.EnvironmentVariables["CLIPPEDAI_DATA_DIR"] = baseDir;
            psi.EnvironmentVariables["CLIPPEDAI_RUNTIME"] = runtimeDir;

            try
            {
                Process p = new Process();
                p.StartInfo = psi;

                FileStream logStream = new FileStream(pyLog, FileMode.Create, FileAccess.Write, FileShare.ReadWrite);
                StreamWriter sw = new StreamWriter(logStream) { AutoFlush = true };

                p.OutputDataReceived += (s, e) => { if (e.Data != null) sw.WriteLine("[OUT] " + e.Data); };
                p.ErrorDataReceived += (s, e) => { if (e.Data != null) sw.WriteLine("[ERR] " + e.Data); };

                p.Start();
                p.BeginOutputReadLine();
                p.BeginErrorReadLine();

                p.WaitForExit();

                sw.Flush();
                logStream.Flush();
                sw.Close();
                logStream.Close();

                File.AppendAllText(logFile, string.Format("[{0}] Python process exited with code {1}\n", DateTime.Now, p.ExitCode));
            }
            catch (Exception ex)
            {
                try
                {
                    File.AppendAllText(logFile, "[" + DateTime.Now + "] Launch exception: " + ex.ToString() + "\n");
                }
                catch { }
                System.Windows.Forms.MessageBox.Show(
                    "Clipify AI failed to start: " + ex.Message,
                    "Clipify AI Error",
                    System.Windows.Forms.MessageBoxButtons.OK,
                    System.Windows.Forms.MessageBoxIcon.Error
                );
            }
        }

        static void OpenAppWindow(string url)
        {
            string progFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string progFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

            string[] candidates = new string[]
            {
                Path.Combine(progFiles, "Google", "Chrome", "Application", "chrome.exe"),
                Path.Combine(progFilesX86, "Google", "Chrome", "Application", "chrome.exe"),
                Path.Combine(localAppData, "Google", "Chrome", "Application", "chrome.exe"),
                Path.Combine(progFilesX86, "Microsoft", "Edge", "Application", "msedge.exe"),
                Path.Combine(progFiles, "Microsoft", "Edge", "Application", "msedge.exe")
            };

            foreach (var b in candidates)
            {
                if (File.Exists(b))
                {
                    try
                    {
                        Process.Start(new ProcessStartInfo
                        {
                            FileName = b,
                            Arguments = "--app=" + url + " --window-size=1440,900",
                            UseShellExecute = true
                        });
                        return;
                    }
                    catch { }
                }
            }

            try
            {
                Process.Start(url);
            }
            catch { }
        }
    }
}
