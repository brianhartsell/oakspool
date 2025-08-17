import asyncio
import websockets
import json
from ffmpeg import FFmpeg

WS_URL = "ws://localhost:3000"
CAMERA_NAME = "Flow"
FRAME_PATH = "flow_reading.jpg"
STREAM_PATH = "livestream.mp4"

async def get_camera_id(ws):
    await ws.send(json.dumps({
        "messageId": "1",
        "command": "listDevices"
    }))
    response = await ws.recv()
    devices = json.loads(response).get("data", [])
    for device in devices:
        if device.get("name") == CAMERA_NAME:
            return device.get("serialNumber")
    return None

async def start_stream(ws, serial):
    await ws.send(json.dumps({
        "messageId": "2",
        "command": "startLivestream",
        "serialNumber": serial
    }))
    await asyncio.sleep(10)  # Buffer stream

async def stop_stream(ws, serial):
    await ws.send(json.dumps({
        "messageId": "3",
        "command": "stopLivestream",
        "serialNumber": serial
    }))

def extract_frame():
    ffmpeg = (
        FFmpeg()
        .input(STREAM_PATH)
        .output(FRAME_PATH, vf="select=eq(n\\,10)", vframes=1)
    )
    ffmpeg.execute()

async def main():
    async with websockets.connect(WS_URL) as ws:
        serial = await get_camera_id(ws)
        if not serial:
            print("Camera not found.")
            return
        await start_stream(ws, serial)
        await stop_stream(ws, serial)
        extract_frame()
        print(f"Frame saved to {FRAME_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
