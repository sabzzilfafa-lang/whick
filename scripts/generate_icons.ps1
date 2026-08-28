# Suno Helper 시작/종료 아이콘 생성 (256x256 ICO)
param(
    [string]$OutDir = (Join-Path $PSScriptRoot "..\assets\icons")
)

Add-Type -AssemblyName System.Drawing

function New-RoundedRectPath {
    param([float]$X, [float]$Y, [float]$W, [float]$H, [float]$R)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $R * 2
    $path.AddArc($X, $Y, $d, $d, 180, 90)
    $path.AddArc($X + $W - $d, $Y, $d, $d, 270, 90)
    $path.AddArc($X + $W - $d, $Y + $H - $d, $d, $d, 0, 90)
    $path.AddArc($X, $Y + $H - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    return $path
}

function Save-SunoIcon {
    param(
        [ValidateSet("start", "stop")]
        [string]$Type,
        [string]$Path
    )

    $size = 256
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.Clear([System.Drawing.Color]::Transparent)

    $pad = 28
    $rect = New-Object System.Drawing.Rectangle $pad, $pad, ($size - $pad * 2), ($size - $pad * 2)
    $radius = 52

    if ($Type -eq "start") {
        $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
            $rect,
            [System.Drawing.Color]::FromArgb(255, 167, 139, 250),
            [System.Drawing.Color]::FromArgb(255, 109, 40, 217),
            135
        )
    } else {
        $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
            $rect,
            [System.Drawing.Color]::FromArgb(255, 248, 113, 113),
            [System.Drawing.Color]::FromArgb(255, 185, 28, 28),
            135
        )
    }

    $bgPath = New-RoundedRectPath $rect.X $rect.Y $rect.Width $rect.Height $radius
    $g.FillPath($brush, $bgPath)

    $shadow = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(60, 0, 0, 0)), 2
    $g.DrawPath($shadow, $bgPath)

    $white = [System.Drawing.Brushes]::White
    if ($Type -eq "start") {
        $play = @(
            (New-Object System.Drawing.PointF 108, 88),
            (New-Object System.Drawing.PointF 108, 168),
            (New-Object System.Drawing.PointF 178, 128)
        )
        $g.FillPolygon($white, $play)
    } else {
        $stopRect = New-Object System.Drawing.RectangleF 98, 98, 60, 60
        $stopPath = New-RoundedRectPath $stopRect.X $stopRect.Y $stopRect.Width $stopRect.Height 14
        $g.FillPath($white, $stopPath)
        $stopPath.Dispose()
    }

    $bgPath.Dispose()
    $brush.Dispose()

    $icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
    $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Create)
    try {
        $icon.Save($fs)
    } finally {
        $fs.Close()
        $icon.Dispose()
        $g.Dispose()
        $bmp.Dispose()
    }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Save-SunoIcon -Type "start" -Path (Join-Path $OutDir "start.ico")
Save-SunoIcon -Type "stop" -Path (Join-Path $OutDir "stop.ico")
Write-Host "Icons saved to $OutDir"
