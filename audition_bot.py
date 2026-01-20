import time
import threading
import cv2
import numpy as np
import keyboard  
import win32gui
import win32ui
import win32con
import imutils
import random
import ctypes

SCAN_CODES = {
    'up': 72, 'down': 80, 'left': 75, 'right': 77,
    '1': 79, '3': 81, '7': 71, '9': 73,  
    'ctrl': 29, 'space': 57
}
KEY_HOLD_TIME = 0.025  
SAME_KEY_GAP = 0.045   
NORMAL_KEY_GAP = 0.06 
POST_SEQUENCE_CD = 0.8  

def fast_push(key_label, duration):
    sc = SCAN_CODES.get(key_label)
    if sc:
        keyboard.press(sc)
        time.sleep(duration)
        keyboard.release(sc)

class FastWindowCapturer:
    def __init__(self, window_name='Audition'):
        self.window_name = window_name
        self.hwnd, self.m_srcdc, self.m_memdc, self.m_bmp = None, None, None, None

    def _init_res(self, w, h):
        self.hwnd = win32gui.FindWindow(None, self.window_name)
        if not self.hwnd: return False
        try:
            hwin_dc = win32gui.GetWindowDC(self.hwnd)
            self.m_srcdc = win32ui.CreateDCFromHandle(hwin_dc)
            self.m_memdc = self.m_srcdc.CreateCompatibleDC()
            self.m_bmp = win32ui.CreateBitmap()
            self.m_bmp.CreateCompatibleBitmap(self.m_srcdc, w, h)
            self.m_memdc.SelectObject(self.m_bmp)
            return True
        except: return False

    def get_screenshot(self, roi):
        w, h = roi[2], roi[3]
        if self.m_memdc is None:
            if not self._init_res(w, h): return None
        try:
            self.m_memdc.BitBlt((0, 0), (w, h), self.m_srcdc, (roi[0], roi[1]), win32con.SRCCOPY)
            img = np.frombuffer(self.m_bmp.GetBitmapBits(True), dtype='uint8').reshape((h, w, 4))
            return img[..., :3].copy()
        except:
            self.m_memdc = None 
            return None

class AuditionBot:

    KEYS_ROI = (280, 540, 470, 40)
    RADAR_ROI = (420, 523, 260, 15)
    TRIGGER_POINT = 228     
    BASE_SENSITIVITY = 75   
    MIN_BALL_HEIGHT = 6     

    def __init__(self):
        self.running = True

    def start(self):
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print(">> [提醒] 請以管理員權限執行以確保按鍵生效")
        
        print("="*40)
        print("    Audition Auto Bot - Perfect Mode")
        print(f"    同鍵間隔: {SAME_KEY_GAP}s | 異鍵間隔: {NORMAL_KEY_GAP}s")
        print("    F9: 停止    ")
        print("="*40)
        
        keyboard.add_hotkey('f9', self.stop)
 
        t1 = threading.Thread(target=self.loop_keys, daemon=True)
        t2 = threading.Thread(target=self.loop_perfect, daemon=True)
        t1.start()
        t2.start()
        
        while self.running: time.sleep(1)

    def stop(self):
        self.running = False
        print(">> 停止執行")

    def loop_keys(self):
        cap = FastWindowCapturer('Audition')
        last_keys_str = ""
        while self.running:
            img = cap.get_screenshot(self.KEYS_ROI)
            if img is not None and np.mean(img) > 25:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                _, thres = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
                cnts = imutils.grab_contours(cv2.findContours(thres, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE))
                bbs = sorted([cv2.boundingRect(c) for c in cnts if cv2.boundingRect(c)[2] > 15], key=lambda b: b[0])
                
                if bbs:
                    keys = []
                    for bb in bbs:
                        roi_t = thres[bb[1]:bb[1]+bb[3], bb[0]:bb[0]+bb[2]]
                        h, w = roi_t.shape
                        rates = [cv2.countNonZero(roi_t[:, :w//3]), cv2.countNonZero(roi_t[:h//3, :]),
                                 cv2.countNonZero(roi_t[:, 2*w//3:]), cv2.countNonZero(roi_t[2*h//3:, :])]
                        idx = np.array(rates).argsort()[::-1]
                        if rates[idx[1]] / (rates[idx[0]] + 1e-5) < 0.65:
                            res = {0: "left", 1: "up", 2: "right", 3: "down"}[idx[0]]
                        else:
                            pair = tuple(sorted((idx[0], idx[1])))
                            res = {(0,1): "7", (0,3): "1", (1,2): "9", (2,3): "3"}.get(pair, "up")
                        keys.append(res)
                    
                    current_str = "".join(keys)
                    if current_str != last_keys_str:
                        print(f"[KEYS] 執行: {keys}")
                        
                    
                        d_hold = 0.02 if len(keys) >= 9 else KEY_HOLD_TIME
                        
                        prev_k = None
                        for k in keys:
                            if k == prev_k:
                                time.sleep(SAME_KEY_GAP)
                            else:
                                if NORMAL_KEY_GAP > 0: time.sleep(NORMAL_KEY_GAP)
                            
                            fast_push(k, d_hold)
                            prev_k = k
                        
                        last_keys_str = current_str
                        time.sleep(POST_SEQUENCE_CD) 
            else:
                last_keys_str = ""
            time.sleep(0.02) 

    def loop_perfect(self):
        cap = FastWindowCapturer('Audition')
        while self.running:
            raw_base = cap.get_screenshot(self.RADAR_ROI)
            if raw_base is None: 
                time.sleep(0.1)
                continue
            base_gray = cv2.cvtColor(raw_base, cv2.COLOR_BGR2GRAY)
            
            start_t = time.perf_counter()
            while time.perf_counter() - start_t < 1.5 and self.running:
                raw_current = cap.get_screenshot(self.RADAR_ROI)
                if raw_current is None: break
                current_gray = cv2.cvtColor(raw_current, cv2.COLOR_BGR2GRAY)
                diff = cv2.absdiff(current_gray, base_gray)
                
                _, pre_thresh = cv2.threshold(diff, self.BASE_SENSITIVITY, 255, cv2.THRESH_BINARY)
                noise_ratio = np.count_nonzero(pre_thresh) / (pre_thresh.shape[0] * pre_thresh.shape[1])
                
                if noise_ratio > 0.30: 
                    base_gray = current_gray
                    continue
                    
                adj_sens = self.BASE_SENSITIVITY + int(noise_ratio * 120)
                _, thresh = cv2.threshold(diff, adj_sens, 255, cv2.THRESH_BINARY)
                
                found = False
                for x in range(self.TRIGGER_POINT, self.RADAR_ROI[2] - 3):
                    if np.count_nonzero(thresh[:, x]) >= self.MIN_BALL_HEIGHT:
                        fast_push('ctrl', 0.04)
                        print(f"[HIT] Perfect! X={x}")
                        found = True
                        break
                
                if found:
                    time.sleep(1.2) 
                    break 
                time.sleep(0.001)

if __name__ == "__main__":
    bot = AuditionBot()
    bot.start()