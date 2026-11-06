action=querymedialist_sync
同步接口需要等待30秒超时。
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| deviceid  | String  |设备序列号   |   |
| channel  | short | 通道  | 需要搜索的通道，从1开始  |
|  starttime |  String |  开始时间 | 开始时间yyyy-MM-dd HH:mm:ss  |
|  endtime |  String | 结束时间  | 结束时间yyyy-MM-dd HH:mm:ss |
|  mediatype |  short | 资源类型  | 0：音视频 1音频 2视频 3视频或者音视频  |
|  storetype | short  | 存储器类型  | 存储器类型 0:全部存储 1主存储 2灾备存储  |
|  offset |  int | 时区  | 用户浏览器或者app的时区，默认中国时区8  |

