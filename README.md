# pw Video Convertor

Optimal conversion of any video to AV1 or H.265 using a simple quality option.

### Features

- No Python dependencies
- Hardware encoding supported
- Progress bar
- Test mode

Usage of example script:

```shell
./pw-video-convert/conv --quality 5 ./video.mkv ~/output
```

## Options

`--quality -q` - Quality level [1..10]

`--container -c` - Output container `mkv`|`mp4` (default mkv)

`--resolution -r` - Target resolution as `WxH` (e.g. `1920x1080`). The source is fitted
into it without upscaling, centered with black bars when the aspect ratio differs.
The output frame is always aligned to an AV1-supported size (width multiple of 64,
height multiple of 16, minimum 128x80), so the encoder never adds its own padding.

`--software -s` - do not use hardware encoding

`--audio -a` - audio tracks to keep: 1-based comma-separated numbers (e.g. `1,3`).
Track numbers are the position among the audio streams as shown in the plan output
(`a1`, `a2`, ...). Default: keep all audio tracks.

`--add-audio-path -d FILE` - external audio file muxed in as an extra Opus track.
Repeatable. `--add-audio-label LABEL` sets the track title; labels bind to the
nearest file in argument order (`-d a.mp3 --add-audio-label VO -d b.mp3 ...`),
files without a label get `External audio N`.

`--test -t` - test mode: cut 1 minute from the middle and encode samples at q=1,3,5,7,9 into the output directory.

`input` - input file

`output` - output dir or file name (default: same dir as input). The output keeps the
input name with the container extension; an `.out` suffix is added if it would
overwrite the input.

## Packages

#### pw-video-convert

Python package for encoding process.

- ffmpeg must be installed system-wide
- no dependencies
- simple parameter `--quality -q` to configure output video quality
- Hardware encoding acceleration supported
- audio track selector
- changing resolution
- TUI progress bar

#### pw-video-convert-service

Simple Web Service with a FIFO queue of conversion tasks.

- HTTP API for creating tasks
- installation scripts for Linux
- space-saving statistics

#### submitter

A simple PyQt5 dialog box for sending local files. If your encoding service is hosted on a different machine, the local paths must match those on the encoding machine.

- PyQt5, native to the KDE environment, no other dependencies
- Service Menu installer for KDE
- batch submitting
- custom subfolder for output files
