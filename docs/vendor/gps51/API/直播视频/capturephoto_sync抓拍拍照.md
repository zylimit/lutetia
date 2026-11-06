action=capturephoto_sync
同步接口需要等待30秒超时，抓拍成功会返回一个图片的url。
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| deviceid  | String  |设备序列号   |   |
| channelid  | int  | 通道id  | 通道id, 从1开始  |
|  resolution |  int |  分辨率 | 参考分辨率列表  |


//分辨率列表
//	0x01:320*240；
//	0x02:640*480；
//	0x03:800*600；
//	0x04:1024*768;
//	0x05:176*144;[Qcif];
//	0x06:352*288;[Cif];
//	0x07:704*288;[HALF D1];
//	0x08:704*576;[D1]; 
返回数据：
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| status  | int  |请求状态码   |-1 代表异常 6 代表发送成功,并确认收到 8 代表发送超时  |
| cause  | string  | 出错原因  |   |
|  devicemedia |  Object |  上传图片对象 |   |

DeviceMedia字段：
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| deviceid  |  string |设备id   |  |
| fileext  | string  | 文件后缀  |   |
| eventcode |  int |  事件编码 |  0：平台下发指令；1：定时动作；2：抢劫报警触发；3：碰撞侧翻报警触发；其他保留 |
| url  | string  | 文件url  |   |
