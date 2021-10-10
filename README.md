基于API GW, Lambda, DDB实现无服务器消息系统，在亚马逊云中国区测试通过。

## 下载代码

    git clone https://github.com/Chen188/apigw-chat

## 安装依赖环境
pip3 install aws_xray_sdk git+https://github.com/Chen188/chalice.git@1.26.0-fix-cn-region

## 部署

0. 安装并配置 awscli, https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html
1. 创建S3桶, ` aws s3 mb s3://your-bucket-name `
2. 修改 deploy.sh 中的 REGION( 北京区域为 *cn-north-1* , 宁夏区域为 *cn-northwest-1* ) 及 BUCKET. 
3. 执行 ./deploy.sh

## 使用

1. 打开 CloudFormation, https://console.amazonaws.cn/cloudformation/home
2. 选中 APIGWChat 
3. 切换到 *输出* tab
4. 找到 WebsocketConnectEndpointURL ，即为已经创建完成的 API GW wss 连接
5. 安装 wscat, `pip install wscat`
6. wscat -c \<WebsocketConnectEndpointURL\>

```
% wscat -c wss://xxxxxxxx.execute-api.cn-northwest-1.amazonaws.com.cn/api
Connected (press CTRL+C to quit)
> mynickname
< Using nickname: mynickname
Type /help for list of commands.
> /help
< Commands available:
    /help
          显示此消息
    /join {chat_room_name}
          加入名为{chat_room_name}的聊天室
    /nick {nickname}
          将您的名字更改为{nickname}。如果没有{nickname}，将打印您的当前姓名
    /room
          打印出您当前房间的名称
    /ls
          如果您在一个房间中，请同时在其中列出所有用户，房间。否则，列出所有房间
    /quit
          离开当前房间

如果您在房间里，无法发送以/开头的消息，并且消息会发送给所有人
```