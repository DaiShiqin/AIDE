# CMAQ Field Map

Use these mappings when translating user questions to CMAQ variables.

## Air Quality Indicators

| User indicator | Preferred field | Unit | Notes |
| --- | --- | --- | --- |
| PM2.5 | `PM25_TOT` | ug/m3 | Main PM2.5 total mass concentration. |
| PM10 | `PM10` | ug/m3 | Main PM10 total mass concentration. |
| O3 hourly | `O3_UGM3` | ug/m3 | Hourly ozone mass concentration. |
| O3 8-hour | `O3_R8` | ug/m3 assumed | Prefer from `_EXTRA` when present; confirm metadata if available. |
| CO | `CO_MGM3` | mg/m3 | Carbon monoxide mass concentration. |
| NO2 | `NO2_UGM3` | ug/m3 | Nitrogen dioxide mass concentration. |
| NO | `NO_UGM3` | ug/m3 | Nitric oxide mass concentration. |
| SO2 | `SO2_UGM3` | ug/m3 | Sulfur dioxide mass concentration. |
| NH3 | `NH3_UGM3` | ug/m3 | Ammonia mass concentration. |
| OX | `OX` | ppbV | O3 plus NO2 oxidant indicator. |

## PM2.5 Components

| Indicator | Field | Unit |
| --- | --- | --- |
| Chloride | `PM25_CL` | ug/m3 |
| Elemental carbon | `PM25_EC` | ug/m3 |
| Sodium | `PM25_NA` | ug/m3 |
| Magnesium | `PM25_MG` | ug/m3 |
| Potassium | `PM25_K` | ug/m3 |
| Calcium | `PM25_CA` | ug/m3 |
| Ammonium | `PM25_NH4` | ug/m3 |
| Nitrate | `PM25_NO3` | ug/m3 |
| Organic carbon | `PM25_OC` | ugC/m3 |
| Soil | `PM25_SOIL` | ug/m3 |
| Sulfate | `PM25_SO4` | ug/m3 |
| Other PM2.5 | `PM25_OTHR` | ug/m3 |

## Meteorology

| Indicator | Field | Unit |
| --- | --- | --- |
| Air density | `AIR_DENS` | kg/m3 |
| Relative humidity | `RH` | % |
| 2m temperature | `TEMP2` | C |
| Solar radiation | `SR` | WATTS/m2 |
| Precipitation | `RT` | mm |
| 10m wind speed | `WSPD10` | m/s |
| 10m wind direction | `WDIR10` | deg |
| Boundary layer height | `PBLH` | m |
| Surface pressure | `PSFC` | hpa |
| Cloud fraction | `CFRAC` | % |
| Cloud base | `CLDB` | Km |
| Visibility | `VIS` | Km |
