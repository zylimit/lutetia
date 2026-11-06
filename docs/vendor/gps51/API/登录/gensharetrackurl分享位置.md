action=gensharetrackurl
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
|  deviceid | String | 设备序列号 | 系统里面唯一确定一台设备  |
|  interval | int | 分享时长 | 从分享时间点开始后的多少分钟允许打开查看轨迹  |


返回值:
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| status  | int  |状态   | 0代表成功 -1代表失败 |
| cause  | String  |状态描述  | OK 代表成功，其他描述代表异常 |
|  deviceid | String | 设备序列号 | 系统里面唯一确定一台设备  |
| shareurl  | String  |分享的URL  | 复制粘贴给用户的分享信息，包含url |
| weburl  | String  |网页URL  | 直接用来打开的url |
