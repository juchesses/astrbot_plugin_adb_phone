# Windows built-in OCR (Windows.Media.Ocr): read text + center coordinates from an image.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File ocr_win.ps1 -Path <image>
# Output: one line per text line:  (x,y)  text
# Note: kept ASCII-only on purpose - PowerShell 5.1 reads BOM-less UTF-8 as ANSI,
#       and non-ASCII comments can break parsing on some systems.
param([Parameter(Mandatory=$true)][string]$Path)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
    $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
}

$full = (Resolve-Path -LiteralPath $Path).ProviderPath
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("zh-Hans-CN"))
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Write-Output "NO_OCR_ENGINE"; exit 1 }

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
if ($result.Lines.Count -eq 0) { Write-Output ""; exit 0 }

$rows = @()
foreach ($line in $result.Lines) {
    $words = $line.Words
    if ($words.Count -eq 0) { continue }
    $minx = 1e9; $maxx = -1e9; $miny = 1e9; $maxy = -1e9
    foreach ($w in $words) {
        $r = $w.BoundingRect
        if ($r.X -lt $minx) { $minx = $r.X }
        if (($r.X + $r.Width) -gt $maxx) { $maxx = $r.X + $r.Width }
        if ($r.Y -lt $miny) { $miny = $r.Y }
        if (($r.Y + $r.Height) -gt $maxy) { $maxy = $r.Y + $r.Height }
    }
    $cx = [int](($minx + $maxx) / 2)
    $cy = [int](($miny + $maxy) / 2)
    $rows += [pscustomobject]@{ Y = $cy; X = $cx; Text = $line.Text }
}

foreach ($row in ($rows | Sort-Object Y, X)) {
    Write-Output ("({0},{1})  {2}" -f $row.X, $row.Y, $row.Text)
}
