# CMAQ Field Map

Use this map to translate user wording into CMAQ variables. First inspect the file because available variables may differ across runs.

## Preferred pollutants

| User wording | Preferred variable | Fallback | Unit expectation |
| --- | --- | --- | --- |
| PM2.5, PM25, fine particulate matter | `PM25_TOT` | `PMIJ` | `ug/m3` |
| PM10, inhalable particulate matter | `PM10` | none | `ug/m3` |
| O3, ozone, hourly ozone | `O3_UGM3` | `O3`, `O3_CLASSIC` | `ug/m3` or `ppbV` |
| O3 8-hour, MDA8, 8-hour ozone | `O3_R8` from `_EXTRA` | calculate from `O3_UGM3` only if asked | usually `ug/m3`, confirm if metadata is absent |
| NO2, nitrogen dioxide | `NO2_UGM3` | `NO2` | `ug/m3` or `ppbV` |
| NO, nitric oxide | `NO_UGM3` | `NO` | `ug/m3` or `ppbV` |
| SO2, sulfur dioxide | `SO2_UGM3` | `SO2` | `ug/m3` or `ppbV` |
| CO, carbon monoxide | `CO_MGM3` | `CO` | `mg/m3` or `ppbV` |
| NH3, ammonia | `NH3_UGM3` | `NH3` | `ug/m3` or `ppbV` |
| VOC, volatile organic compounds | `VOC` | component VOC fields | `ppbC` |

For compatibility with Chinese requests, recognize `细颗粒物`, `可吸入颗粒物`, `臭氧`, `二氧化氮`, `一氧化氮`, `二氧化硫`, `一氧化碳`, `氨`, and `挥发性有机物` as localized aliases for the entries above.

## PM2.5 components

Use these when the user asks for composition, source-like components, or contribution:

`PM25_CL`, `PM25_EC`, `PM25_NA`, `PM25_MG`, `PM25_K`, `PM25_CA`, `PM25_NH4`, `PM25_NO3`, `PM25_OC`, `PM25_SOIL`, `PM25_SO4`, `PM25_OTHR`.

## Meteorology

| User wording | Variable | Unit |
| --- | --- | --- |
| temperature | `TEMP2` | `C` |
| relative humidity | `RH` | `%` |
| wind speed | `WSPD10` | `m/s` |
| wind direction | `WDIR10` | `deg` |
| precipitation | `RT` | `mm` |
| boundary-layer height | `PBLH` | `m` |
| surface pressure | `PSFC` | `hPa` |
| visibility | `VIS` | `km` |

Localized meteorological aliases include `气温`, `相对湿度`, `风速`, `风向`, `降水`, `边界层`, `气压`, and `能见度`.

## Threshold defaults

Use these only as plotting reference lines unless the user specifies another standard:

- PM2.5: 35 and 75 `ug/m3`.
- PM10: 50 and 150 `ug/m3`.
- O3 hourly: 160 and 200 `ug/m3`.
- O3 8-hour: 100 and 160 `ug/m3`.
- NO2: 100 and 200 `ug/m3`.
- SO2: 150 and 500 `ug/m3`.
- CO: 4 and 10 `mg/m3`.
