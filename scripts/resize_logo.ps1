param(
    [Parameter(Mandatory = $true)][string]$LogoSource,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$source = [System.Drawing.Image]::FromFile($LogoSource)
try {
    # The supplied artwork is centered; its full symbol fits in this square crop.
    $side = [Math]::Min($source.Width, $source.Height)
    $left = [int][Math]::Floor(($source.Width - $side) / 2)
    $top = [int][Math]::Floor(($source.Height - $side) / 2)
    $sourceRectangle = [System.Drawing.Rectangle]::new($left, $top, $side, $side)
    foreach ($size in @(16, 24, 32, 48, 64, 128, 256, 512)) {
        # Supersampling keeps the transparent rounded corners smooth at small icon sizes.
        $renderSize = $size * 4
        $render = [System.Drawing.Bitmap]::new($renderSize, $renderSize, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $renderGraphics = [System.Drawing.Graphics]::FromImage($render)
        $rounding = [System.Drawing.Drawing2D.GraphicsPath]::new()
        $bitmap = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $attributes = [System.Drawing.Imaging.ImageAttributes]::new()
        try {
            $diameter = [single]($renderSize * 0.4)
            $far = [single]($renderSize - $diameter)
            $rounding.AddArc([single]0, [single]0, $diameter, $diameter, [single]180, [single]90)
            $rounding.AddArc($far, [single]0, $diameter, $diameter, [single]270, [single]90)
            $rounding.AddArc($far, $far, $diameter, $diameter, [single]0, [single]90)
            $rounding.AddArc([single]0, $far, $diameter, $diameter, [single]90, [single]90)
            $rounding.CloseFigure()
            $renderGraphics.Clear([System.Drawing.Color]::Transparent)
            $renderGraphics.SetClip($rounding)
            $renderGraphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $renderGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $renderGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $renderGraphics.DrawImage($source, [System.Drawing.Rectangle]::new(0, 0, $renderSize, $renderSize),
                $sourceRectangle, [System.Drawing.GraphicsUnit]::Pixel)
            $graphics.Clear([System.Drawing.Color]::Transparent)
            $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
            $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $attributes.SetWrapMode([System.Drawing.Drawing2D.WrapMode]::TileFlipXY)
            $destination = [System.Drawing.Rectangle]::new(0, 0, $size, $size)
            $graphics.DrawImage($render, $destination, 0, 0,
                $renderSize, $renderSize,
                [System.Drawing.GraphicsUnit]::Pixel, $attributes)
            $bitmap.Save((Join-Path $OutputDirectory "$size.png"), [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally {
            $attributes.Dispose()
            $graphics.Dispose()
            $bitmap.Dispose()
            $rounding.Dispose()
            $renderGraphics.Dispose()
            $render.Dispose()
        }
    }
}
finally {
    $source.Dispose()
}
