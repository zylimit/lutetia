action=startvideos_sync
同步接口需要等待30秒超时，播放成功后，需要开启一个3分钟的timer，主动调用停止播放，提示用户播放时间到了。
后面会3分半主动停止播放，避免用户突然播放不了。
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| deviceid  | String  |设备序列号   |   |
| channels  | List<Short>  | 通道列表[1,2,3,4]  | 需要播放的通道列表  |
|  datatype |  short |  播放数据类型 | 建议用0直播，0 音视频 1 视频 2 双向对讲 3 监听 4 中心广播 5 透传  |
|  playtype |  String | 播放方式  | “rtmp”， “flvs”，网页建议用flvs,app和小程序用rtmp |

返回数据：
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| status  | int  |请求状态码   |参考下表回复状态status字段说明 |
| cause  | string  | 出错原因  |   |
|  records |  List |  通道列表 |   |

通道数据：
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| channel  | int  |通道id   |从1开始代表第一个通道 |
| hasaudio  | int  | 是否带语音（已经废除）  |  -1 自动 0 无 1 有 |
|  playurl |  String | 音视频播放地址(已经废除)  | https://video1.gps51.com:82/live/19000012029_1_0_1078_video.flv  |
|  playurlaudio |  String | 语音播放地址  | https://video1.gps51.com:82/live/19000012029_1_0_1078_audio.flv  |
|  playurlvideo |  String | 视频播放地址  | https://video1.gps51.com:82/live/19000012029_1_0_1078_video.flv  |
|  uploadurlaudio |  String | 对讲上传语音的地址  |   |

回复状态status字段说明
|状态枚举|状态值|状态说明|
|---|---|---|
|CMD_SEND_RESULT_UNKONWN|-1|未知错误|
|CMD_SEND_RESULT_UNCONFIRM|0|发送成功，未收到确认|
|CMD_SEND_RESULT_PASSWORD_ERROR|1|密码错误|
|CMD_SEND_RESULT_OFFLINE_NOT_CACHE|2|设备离线，未缓存|
|CMD_SEND_RESULT_OFFLINE_CACHED|3|设备离线，已缓存|
|CMD_SEND_RESULT_MODIFY_DEFAULT_PASSWORD|4|需要修改默认密码|
|CMD_SEND_RESULT_DETAIL_ERROR|5|未知错误|
|CMD_SEND_CONFIRMED|6|发送成功,并确认收到|
|CMD_SEND_OVER_RETRY_TIMES|7|尝试发送3次失败|
|CMD_SEND_SYNC_TIMEOUT|8|同步消息发送后超过60秒没收到确认|

