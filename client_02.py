import requests
import time
import pyautogui

server_ip = "http://127.0.0.1:5000"
client_id = "pc_02"

# image=pyautogui.screenshot()
# image.save("screenshot.png")                          
# print("the screentshot save in screenshot.png")

while True:
    try:
        res=requests.get(f"{server_ip}/get_command/{client_id}")
        data=res.json()
        command=data.get("command")
        if command and command.lower() == "take screenshot" :
            print(f"command for {client_id} : {command}")           
            image=pyautogui.screenshot()
            image.save(f"{client_id}.png")
            print("the screentshot save in screenshot.png")

            with open(f"{client_id}.png", "rb") as ss:
                requests.post(f"{server_ip}/upload/{client_id}",files={"screenshot": ss})
            
        elif command :
            print(f"command for {client_id} : {command}")           
        else:
            print("no command from server")
    except Exception as e:
        print("error",e)

    time.sleep(10)                                          