import datetime, time



class chat_time_utils(object):
    """时间相关的工具函数"""
    @staticmethod
    def add_minutes(min):
        """返回输入数量之后的unix时间戳

        :param min: 分钟数
        """
        nowadd = datetime.datetime.now() + datetime.timedelta(minutes=min)

        return int(time.mktime(nowadd.timetuple()))