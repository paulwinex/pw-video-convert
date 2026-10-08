# pw Video Convertor

Optimal conversion any video to AV1 or H265 using simple quality option.

### Features

- No dependencies
- Hardware encoding supported
- Progress bar
- Test mode

Example:

```shell
python3 ./pw_video_convert --quality 5 ./video.mkv ~/output
```

## Options

`--quality -q` - Quality level [1..10]

`--container -c` - Output container `mkv`|`mp4` (default mkv)

`--resolution -r` - Target frame size as `WxH` (e.g. `1920x1080`). The source is fitted
into it without upscaling, centered with black bars when the aspect ratio differs.
The output frame is always aligned to an AV1-supported size (width multiple of 64,
height multiple of 16, minimum 128x80), so the encoder never adds its own padding.

`--software -s` - do not use hardware encoding

`-t --test` - text mode: cut 1 minute from the middle and encode samples at q=1,3,5,7,9 into the output directory

`input` - input file

`output` - output dir or file name (default: same dir as input). The output keeps the
input name with the container extension; an `.out` suffix is added if it would
overwrite the input.

