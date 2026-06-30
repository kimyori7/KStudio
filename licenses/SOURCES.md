FFmpeg - Corresponding Source & Provenance (GPL v3 section 6)
=============================================================

KStudio bundles a prebuilt FFmpeg binary (bin/ffmpeg.exe) and invokes it as a
separate process (KStudio's own Python code is not a derivative work of FFmpeg).
The bundled FFmpeg binary itself is licensed under the GNU General Public
License, version 3, and statically links the GPL components x264, x265, and
xvidcore. KStudio therefore makes the Corresponding Source available as required
by GPL v3 section 6, via the written offer below.

Exact binary shipped:
  ffmpeg version 2026-04-19-git-de18feb0f0-essentials_build-www.gyan.dev
  built with gcc 15.2.0 (Rev13, Built by MSYS2 project)

Upstream FFmpeg source (permanent, addressable by commit):
  https://github.com/FFmpeg/FFmpeg/commit/de18feb0f0

Binary build distributor (permanent archive of this exact build):
  https://github.com/GyanD/codexffmpeg/releases/tag/2026-04-19-git-de18feb0f0

Build configuration (GPL; statically links x264/x265/xvid):
  --enable-gpl --enable-version3 --enable-static --disable-w32threads
  --disable-autodetect --enable-cairo --enable-fontconfig --enable-iconv
  --enable-gnutls --enable-libxml2 --enable-gmp --enable-bzlib --enable-lzma
  --enable-zlib --enable-libsrt --enable-libssh --enable-libzmq --enable-avisynth
  --enable-sdl2 --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxvid
  --enable-libaom --enable-libopenjpeg --enable-libvpx --enable-mediafoundation
  --enable-libass --enable-libfreetype --enable-libfribidi --enable-libharfbuzz
  --enable-libvidstab --enable-libvmaf --enable-libzimg --enable-amf
  --enable-cuda-llvm --enable-cuvid --enable-dxva2 --enable-d3d11va --enable-d3d12va
  --enable-ffnvcodec --enable-libvpl --enable-nvdec --enable-nvenc --enable-vaapi
  --enable-openal --enable-libgme --enable-libopenmpt --enable-libopencore-amrwb
  --enable-libmp3lame --enable-libtheora --enable-libvo-amrwbenc --enable-libgsm
  --enable-libopencore-amrnb --enable-libopus --enable-libspeex --enable-libvorbis
  --enable-librubberband

WRITTEN OFFER (valid for three years from the date you received this copy):
  You may obtain the complete Corresponding Source for the bundled FFmpeg binary
  - the FFmpeg source at the commit above, the source of the statically-linked
  GPL libraries (x264, x265, xvidcore) at the versions used, and the scripts to
  control compilation and installation - at no charge beyond the reasonable cost
  of distribution. Request it by opening an issue at:
      https://github.com/kimyori7/KStudio-releases/issues
  When a release ships this FFmpeg build, a corresponding-source archive is also
  attached to that release where practical.

The full GPL v3 text appears in the "GNU GENERAL PUBLIC LICENSE (v3)" section of
THIRD-PARTY-LICENSES.txt.
