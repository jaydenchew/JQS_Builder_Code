import requests
import time
url = "http://127.0.0.1:8082/MyWcfService/getstring"
#获取资源号
params = {
    "duankou": "COM3",
    "hco": 0,
    "daima": 0
}
response = requests.get(url, params=params)
print(response.text)

zyh_int=eval(response.text)
print(zyh_int)

#移动
time.sleep(4)       
params = {
    "duankou": "0",
    "hco":zyh_int,
    "daima": "x100y100"
}
a = requests.get(url, params=params)
print(a.text)

#按下
time.sleep(0.5)    
params = {
    "duankou": "0",
    "hco":zyh_int,
    "daima": "z6"
}
a = requests.get(url, params=params)
print(a.text)

#抬起
time.sleep(0.08)    
params = {
    "duankou": "0",
    "hco":zyh_int,
    "daima": "z0"
}
a = requests.get(url, params=params)
print(a.text)

#复位
time.sleep(1)       
params = {
    "duankou": "0",
    "hco":zyh_int,
    "daima": "x0y0"
}
a = requests.get(url, params=params)
print(a.text)

#关闭端口
time.sleep(1)       
params = {
    "duankou": "0",
    "hco":zyh_int,
    "daima": "0"
}
a = requests.get(url, params=params)
print(a.text)



