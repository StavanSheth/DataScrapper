Add-Type -AssemblyName System.Drawing

$srcPath = "C:\Users\Stavan\.gemini\antigravity-ide\brain\39398282-5a91-446c-b5a3-a726ba37ecaf\platform_scraper_icon_1792432901760.jpg"
if (-not (Test-Path $srcPath)) {
    Write-Error "Source image not found: $srcPath"
    exit 1
}

$srcImg = [System.Drawing.Image]::FromFile($srcPath)

$destDirs = @(
    "c:\Projects\Data Scrapper\1_Linkedin_Platforms\apps\extension\icons",
    "c:\Projects\Data Scrapper\1_Linkedin_Platforms\apps\extension",
    "c:\Projects\Data Scrapper\extension\icons",
    "c:\Projects\Data Scrapper\extension"
)

foreach ($dir in $destDirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

$sizes = @(16, 32, 48, 128)

foreach ($sz in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap $sz, $sz
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.DrawImage($srcImg, 0, 0, $sz, $sz)
    $g.Dispose()

    foreach ($dir in $destDirs) {
        $outPath = Join-Path $dir ("icon" + $sz + ".png")
        $bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
        Write-Output "Saved: $outPath ($sz x $sz)"
    }
    $bmp.Dispose()
}

# Also save icon.png as 128px default
$bmp128 = New-Object System.Drawing.Bitmap 128, 128
$g128 = [System.Drawing.Graphics]::FromImage($bmp128)
$g128.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g128.DrawImage($srcImg, 0, 0, 128, 128)
$g128.Dispose()

foreach ($dir in $destDirs) {
    $outPath = Join-Path $dir "icon.png"
    $bmp128.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
    Write-Output "Saved default: $outPath"
}
$bmp128.Dispose()
$srcImg.Dispose()

Write-Output "All icon sizes (16, 32, 48, 128) generated successfully!"
