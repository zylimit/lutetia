目前支持两种转发：
解析后的json数据转发和原始报文转发，文档只说明json格式。

| 参数 |数据类型 |说明   |详细说明   |
|---|---|---|---|
|  devicename | String | 设备名称 | 可以在网站上修改名称  |
| deviceid  |  String | 设备id  | 设备id，唯一序列号  |  
|  lat | double  |   纬度| wgs84格式的纬度  | 
|  lon | double  |  经度 | wgs84格式的经度  |  
|  arrivedtime |  long |  服务器接收时间 |  utc 时间  | 
|  updatetime |  long |  更新时间，用这个时间排序轨迹 |  utc 时间  |  
|  validpoistiontime  |long   | 最后定位时间  |  最后有效的定位时间utc (字段拼写错误，一直沿用) |  
|  radius |  double |  精度半径 | 定位半径 单位米  |  
|  speed |  double |  速度 |  速度 单位米 |
|  altitude |  double | 高度  | 高度 米  |
|  course | int  |  角度 |  角度 方向 0~360度 |
|  totaldistance | int  |  总里程 |  服务器计算的总里程米 |
|  status |  long | 状态  |  没有太多用 |
|  strstatus | String  | 状态描述  |   可用来显示状态|
|  alarm |  long |  报警 | 报警  |
| stralarm  | String  |  报警描述 |  可用来显示报警 |
|  gotsrc | String  |  定位类型 |cell wifi gps 定位类型   |
|  rxlevel |  int | 接收信号强度 百分比  | 10 40 60 80 100 这个固定值  |
|  voltagev | double  |  电压V | 电压V，有的设备没有电压  |
|  voltagepercent | int  |  电量百分比| 有的设备百分比是通过上报次数计算百分比  |
|  gpsvalidnum | int  |  卫星个数| 卫星个数  |
|  iostatus | int  |  io状态| io状态,默认-1 |
|  rotatestatus | int  |  正反转| 默认-1,0:未知,1：正转（空车）2:反转（重车）,3：停转  |
|  reportmode | short  |  上报模式| 参考上报模式列表  |
|  moving | int  |  是否在运动| 是否在运动 0代表没运动 1代表在运动 判断依据当前位置跟上一次的位置是否超过1米  |
|  fuledata | UniFuelData  |  油耗信息| 参考下面油耗数据说明  | 
|  tempdata | SuperviseTemp  |  温湿度信息| 参考下面温湿度数据说明  | 
|  parkduration | long  |  停留了多久| 停留了多久，毫秒数  |
|  devicealarm | Object  |  报警对象| 默认为null，单独的报警记录，可以不处理其他数据，只处理devicealarm[报警数据格式](https://gitee.com/terry3/gwebmgr/wikis/Api/%E6%95%B0%E6%8D%AE%E8%BD%AC%E5%8F%91/%E8%BD%AC%E5%8F%91%E6%8A%A5%E8%AD%A6%E6%B6%88%E6%81%AF)  |

上报模式
| 值  | 描述  |
|---|---|
| 0x00  | 定时上报  |
| 0x01  | 定距上报  |
| 0x02 |  拐点上传 |
| 0x03  | ACC 状态改变上传  |
| 0x04  | 从运动变为静止状态后，补传最后一个定位点  |
| 0x05  | 网络断开重连后，上报之前最后一个有效上传点  |
| 0X06  | 星历更新强制上传 GPS 点  |
| 0X07  | 按键上传定位点  |
| 0X08   | 开机上报位置信息  |
| 0X09  | 未使用  |
| 0X0A  | 设备静止后上报最后的经纬度，但时间更新  |
| 0X0B  | WIFI 解析经纬度上传包  |
| 0X0C  | 上报模式：LJDW（立即定位）指令上报  |
| 0X0D  | 设备静止后上报最后的经纬度  |
| 0X0E  | GPSDUP 上传（下静止状态定时上传）  |

