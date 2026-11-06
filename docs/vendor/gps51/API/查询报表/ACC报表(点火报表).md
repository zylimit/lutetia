action=reportaccsbytime
根据设备的ACC点火和熄火形成的记录报表
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| deviceids  | List<String>  |设备序列号列表   |   |
|  starttime |  String |  开始时间 | 开始时间yyyy-MM-dd HH:mm:ss  |
|  endtime |  String | 结束时间  | 结束时间yyyy-MM-dd HH:mm:ss |
|  offset |  int | 时区  | 默认是8中国时区  |

返回值:
| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| status  | int  |查询状态   |0表示成功，其他表示失败   |
| cause  | String  |查询错误原因说明   |OK表示成功，其他表示失败原因   |
| records  | List  |查询列表   |具体查看列表字段说明  |

列表字段说明：

| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
| accstateid  | String  |记录的uuid 唯一确定这一条记录   |   |
| accstate  | int  |acc状态   | 0 无 2 关 3 开  |
| begintime  | long  |开始时间 毫秒数数   |   |
| endtime  | long  |结束时间 毫秒数数    |   |
| slat  | float  |开始纬度   |度分秒   |
| slon |  float |  开始经度 |  度分秒 |
| elat  | float  |结束纬度   |   度分秒|
| elon |  float |  结束经度 | 度分秒  |
