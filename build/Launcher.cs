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
                pythonExe = Path.Combine(baseDir, ".venv", "Scripts", "pythonw.exe");
            }
            if (!File.Exists(pythonExe))
            {
                pythonExe = "python.exe";
            }

            // 3. Launch app.py
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonExe;
            psi.Arguments = "\"" + appPy + "\"";
            psi.WorkingDirectory = baseDir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;

            try
            {
                Process p = Process.Start(psi);
                if (p != null)
                {
                    p.WaitForExit();
                }
            }
            catch (Exception ex)
            {
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
