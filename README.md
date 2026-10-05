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

`--software -s` - do not use hardware encoding

`-t --test` - text mode: cut 1 minute from the middle and encode samples at q=1,3,5,7,9 into the output directory

`input` - input file

`output` - output dir or file name (default: current workdir)

