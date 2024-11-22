# AGTV2STRM

Convert Apollo Group TV M3U lists to STRM files,
Extracts media (TV Show / Movie) details (Title, release date) from The Movie DB (TMDB).

## How it works

First execution can take up to 5 minutes to create all STRM files (~113k media streams), after then, it will fetch only gaps (~15 seconds),
Interval of executions is 1 minute.

| Stage                                                 | Duration    | More details                                                                              |
| ----------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------- |
| Load up to date M3U list from Apollo Group TV         | 3 seconds   | Any cycle                                                                                 |
| Extract streams (Movies / TV Episodes) from M3U lists | 1 second    | Any cycle                                                                                 |
| Load media details from TMDB                          | 120 seconds | Initial load is about 15k titles, once cache available, only new titles will be retrieved |
| Merge data of TMDB into streams                       | 2 seconds   | Any cycle                                                                                 |
| Created unique directories under `/app/media`         | 11 seconds  | First cycle only                                                                          |
| Build STRM files under the `/app/media` directory     | 130 seconds |                                                                                           |
| List invalid streams that were not processed          | 0           | Use case: AGTV reported stream as `movie`, TMDB reported it as `tvshow`                   |

### Cache

For faster loading of data and debugging, cache directory located at `/app/cache`,
It is highly suggested to map to volume to avoid losing information after redeploy image.

- `agtv.json` - M3U list from Apollo Group TV - Debug only
- `streams.json` - Streams details
- `tmdb.json` - TMDB details

## How to install

### Prerequisites

- Apollo Group TV account
- [The Movie DB](https://www.themoviedb.org/) account with API Read Access Token

### Docker Compose

```dockerfile
version: '3'
services:
  agtv2strm:
    image: "registry.gitlab.com/elad.bar/agtv2strm:latest"
    container_name: "agtv2strm"
    hostname: "agtv2strm"
    restart: "unless-stopped"
    environment:
      - AGTV_USERNAME=Username
      - AGTV_PASSWORD=Password
      - TMDB_API_KEY=APIKEY
      - SCAN_INTERVAL=60
      - AGTV_MAX_TV_SHOWS_PAGES=25
      - DEBUG=False
    volumes:
      - $PWD/media:/app/media
      - $PWD/cache:/app/cache
```

### Environment Variables

| Variable                | Default | Required | Description                                          |
| ----------------------- | ------- | -------- | ---------------------------------------------------- |
| AGTV_USERNAME           | -       | +        | Username to Apollo Group TV service                  |
| AGTV_PASSWORD           | -       | +        | Password of the AGTV account                         |
| AGTV_MAX_TV_SHOWS_PAGES | 25      | -        | Pages of TV Shows to scan                            |
| TMDB_API_KEY            | -       | +        | The Movie DB API Read Access Token                   |
| SCAN_INTERVAL           | 60      | -        | Scan interval in minutes, default - every 60 minutes |
| DEBUG                   | false   | -        | Enable debug log messages                            |
