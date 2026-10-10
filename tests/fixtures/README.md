# Synthetic ingestion fixture

`source.mp4` contains only generated test patterns and a generated sine wave; no
personal media or third-party content. It is a 320x240 H.264/AAC MP4 lasting 2.52
seconds (authoritative credit duration rounds up to 3 seconds), approximately
161 KB. It is committed so tests never fetch public media or call paid services.

Regenerate using FFmpeg (the verified Linux build is recorded in implementation status):

```sh
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=320x240:rate=25 \
  -f lavfi -i sine=frequency=440:sample_rate=16000 -t 2.5 -c:v libx264 \
  -threads 1 -crf 16 -pix_fmt yuv420p -c:a aac -b:a 64k -movflags +faststart \
  -y tests/fixtures/source.mp4
```

Set `FFPROBE_BINARY` to a reviewed local ffprobe executable if it is not on PATH.
Linux/CI installs the distro FFmpeg package. Tests fail if media validation is
unavailable; a missing validator is never treated as successful ingestion.
