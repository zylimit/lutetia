action=playrecordcontrol_sync
同步接口需要等待30秒超时，播放成功后，需要开启一个3分钟的timer，主动调用停止播放，提示用户播放时间到了。
后面会3分半主动停止播放，避免用户突然播放不了。
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| deviceid  | String  |设备序列号   |   |
| channel | short  | 通道  | 需要回放的通道，从1开始  |
|  playcontrol |  short |  回放控制 | 0：开始回放 1:暂停回放 2:结束回放3:快进回放4:关键帧快退回放5:拖动回放6：关键帧回放  |
|  playrate |  short | 播放速率  | 快进或快退倍数 0：无效 1：1倍 2:2倍 3:4倍 4:8倍 5:16倍 |
|  playtype |  String | 播放方式  | “rtmp”， “flv”，网页建议用flv,app和小程序用rtmp |
|  starttime |  String |  开始时间 | 开始时间yyyy-MM-dd HH:mm:ss  |
|  endtime |  String | 结束时间  | 结束时间yyyy-MM-dd HH:mm:ss |
|  offset |  int | 时区  | 用户浏览器或者app的时区，默认中国时区8  |
