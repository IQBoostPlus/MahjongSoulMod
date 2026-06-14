using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace MahjongSoulMod.Setup;

class Program
{
    static async Task Main(string[] args)
    {
        Console.WriteLine("========================================");
        Console.WriteLine("  MahjongSoul AutoMod v1.0 Installer");
        Console.WriteLine("========================================");
        Console.WriteLine();

        // Detect game directory
        string gameDir = DetectGameDir();
        if (gameDir == null)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("ERROR: MahjongSoul game not found!");
            Console.WriteLine();
            Console.ResetColor();
            Console.WriteLine("Expected locations checked:");
            Console.WriteLine("  D:\\Steam\\steamapps\\common\\MahjongSoul");
            Console.WriteLine("  C:\\Program Files (x86)\\Steam\\steamapps\\common\\MahjongSoul");
            Console.WriteLine("  C:\\Program Files\\Steam\\steamapps\\common\\MahjongSoul");
            Console.WriteLine();
            Console.Write("Enter game path manually: ");
            string? custom = Console.ReadLine();
            if (!string.IsNullOrEmpty(custom) && Directory.Exists(custom))
                gameDir = custom;
            else
            {
                Console.WriteLine("Invalid path. Press Enter to exit.");
                Console.ReadLine();
                return;
            }
        }

        Console.WriteLine($"Game directory: {gameDir}");
        Console.WriteLine();

        // Step 1: Install BepInEx if needed
        bool hasBepInEx = File.Exists(Path.Combine(gameDir, "winhttp.dll"));
        if (!hasBepInEx)
        {
            Console.Write("Downloading BepInEx 6 IL2CPP... ");
            try
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
                var zipBytes = await client.GetByteArrayAsync(
                    "https://github.com/BepInEx/BepInEx/releases/download/v6.0.0-pre.2/" +
                    "BepInEx-Unity.IL2CPP-win-x86-6.0.0-pre.2.zip");

                Console.WriteLine("OK");
                Console.Write("Extracting... ");

                var zipPath = Path.Combine(Path.GetTempPath(), "bepinex_x86.zip");
                await File.WriteAllBytesAsync(zipPath, zipBytes);
                ZipFile.ExtractToDirectory(zipPath, gameDir, overwriteFiles: true);
                File.Delete(zipPath);

                Console.WriteLine("OK");
            }
            catch (Exception ex)
            {
                Console.ForegroundColor = ConsoleColor.Red;
                Console.WriteLine($"FAILED: {ex.Message}");
                Console.ResetColor();
                Console.WriteLine("\nPress Enter to exit...");
                Console.ReadLine();
                return;
            }
        }
        else
            Console.WriteLine("BepInEx already installed (skipped)");

        // Step 2: Deploy MOD DLL
        Console.Write("Deploying MahjongSoulMod.dll... ");
        try
        {
            string installerDir = Path.GetDirectoryName(
                Process.GetCurrentProcess().MainModule?.FileName ?? ".") ?? ".";

            // Try multiple locations for the MOD DLL
            string[] searchPaths = [
                Path.Combine(installerDir, "MahjongSoulMod.dll"),
                Path.Combine(Directory.GetCurrentDirectory(), "MahjongSoulMod.dll"),
                @"D:\Code\MahjongSoulMod\bin\Release\net6.0\MahjongSoulMod.dll",
                @"D:\Code\MahjongSoulMod\bin\Debug\net6.0\MahjongSoulMod.dll",
            ];

            string? dllSource = null;
            foreach (var path in searchPaths)
            {
                if (File.Exists(path))
                {
                    dllSource = path;
                    break;
                }
            }

            if (dllSource == null)
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("NOT FOUND");
                Console.WriteLine("Place MahjongSoulMod.dll next to this installer.");
                Console.ResetColor();
            }
            else
            {
                string pluginsDir = Path.Combine(gameDir, "BepInEx", "plugins");
                Directory.CreateDirectory(pluginsDir);
                string dest = Path.Combine(pluginsDir, "MahjongSoulMod.dll");
                File.Copy(dllSource, dest, overwrite: true);
                Console.WriteLine($"OK ({new FileInfo(dest).Length} bytes)");
            }
        }
        catch (Exception ex)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine($"FAILED: {ex.Message}");
            Console.ResetColor();
        }

        // Step 3: Copy Cpp2IL DLLs for metadata v31 support
        Console.Write("Updating IL2CPP metadata support... ");
        string coreDir = Path.Combine(gameDir, "BepInEx", "core");
        string libPath = Path.Combine(coreDir, "LibCpp2IL.dll");
        string cppPath = Path.Combine(coreDir, "Cpp2IL.Core.dll");

        // Check if already updated (v31-capable DLLs are ~180KB+)
        bool needsUpdate = false;
        if (!File.Exists(libPath) || new FileInfo(libPath).Length < 300000)
            needsUpdate = true;
        if (!File.Exists(cppPath) || new FileInfo(cppPath).Length < 350000)
            needsUpdate = true;

        if (!needsUpdate)
        {
            Console.WriteLine("Already up to date");
        }
        else
        {
            // Try to find pre-downloaded Cpp2IL DLLs
            string[] searchDirs = [
                Path.GetDirectoryName(Process.GetCurrentProcess().MainModule?.FileName) ?? ".",
                Path.Combine(Path.GetDirectoryName(Process.GetCurrentProcess().MainModule?.FileName) ?? ".", "cpp2il"),
                coreDir, // Already in BepInEx/core
                @"D:\Code\MahjongSoulMod\setup\cpp2il",
            ];

            string? foundDir = null;
            foreach (var dir in searchDirs)
            {
                if (File.Exists(Path.Combine(dir, "LibCpp2IL.dll")) &&
                    File.Exists(Path.Combine(dir, "Cpp2IL.Core.dll")))
                {
                    foundDir = dir;
                    break;
                }
            }

            if (foundDir != null)
            {
                // Copy from local cache
                File.Copy(Path.Combine(foundDir, "LibCpp2IL.dll"), libPath, true);
                File.Copy(Path.Combine(foundDir, "Cpp2IL.Core.dll"), cppPath, true);
                Console.WriteLine("OK (from local files)");
            }
            else
            {
                Console.ForegroundColor = ConsoleColor.Yellow;
                Console.WriteLine("SKIPPED (no internet for GitHub download)");
                Console.ResetColor();
                Console.WriteLine("  The MOD will try to update this on first game launch.");
                Console.WriteLine("  If Cpp2IL fails, delete BepInEx/cache and restart.");
            }
        }

        Console.WriteLine();
        Console.WriteLine("========================================");
        Console.WriteLine("  Installation Complete!");
        Console.WriteLine("========================================");
        Console.WriteLine();
        Console.WriteLine("1. Launch 雀魂 through Steam");
        Console.WriteLine("2. The MOD will load automatically");
        Console.WriteLine("3. Enter a match to activate auto-play");
        Console.WriteLine();
        Console.WriteLine("Config: BepInEx/config/com.mahjongsoul.automod.cfg");
        Console.WriteLine("Log:    BepInEx/LogOutput.log");
        Console.WriteLine();

        Console.Write("Launch game now? (Y/N): ");
        var key = Console.ReadKey(true);
        if (key.KeyChar == 'y' || key.KeyChar == 'Y')
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = "steam://rungameid/1329410",
                    UseShellExecute = true
                });
                Console.WriteLine("Launching via Steam...");
            }
            catch
            {
                try
                {
                    Process.Start(Path.Combine(gameDir, "Jantama_MahjongSoul.exe"));
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Failed: {ex.Message}");
                }
            }
        }

        Console.WriteLine();
        Console.WriteLine("Press Enter to exit...");
        Console.ReadLine();
    }

    static string? DetectGameDir()
    {
        string[] candidates = [
            @"D:\Steam\steamapps\common\MahjongSoul",
            @"C:\Program Files (x86)\Steam\steamapps\common\MahjongSoul",
            @"C:\Program Files\Steam\steamapps\common\MahjongSoul",
            @"E:\Steam\steamapps\common\MahjongSoul",
        ];

        foreach (var dir in candidates)
        {
            if (Directory.Exists(dir) &&
                File.Exists(Path.Combine(dir, "Jantama_MahjongSoul.exe")))
                return dir;
        }

        // Auto-detect via Steam registry
        try
        {
            using var key = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(
                @"Software\Valve\Steam");
            if (key != null)
            {
                string? steamPath = key.GetValue("SteamPath")?.ToString();
                if (steamPath != null)
                {
                    string libPath = Path.Combine(steamPath, "steamapps", "common", "MahjongSoul");
                    if (Directory.Exists(libPath))
                        return libPath;
                }
            }
        }
        catch { }

        return null;
    }
}
