from database import SessionLocal, engine
import models

def run_seed():
    # 0. 確保資料表已經建立 (非常重要的一行！)
    models.Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    # 1. 建立教授資料
    p1 = models.Professor(professor_name="呂政修", professor_title="教授", department_name="臺灣科技大學電子工程系")
    p2 = models.Professor(professor_name="鄭瑞光", professor_title="教授", department_name="臺灣科技大學電子工程系")
    p3 = models.Professor(professor_name="吳晉賢", professor_title="教授", department_name="臺灣科技大學電子工程系")

    # 2. 建立地點資料
    l1 = models.DefenseLocation(building_name="第二教學大樓", room_number="T2-202", full_location_name="第二教學大樓 T2-202會議室")

    # 把以上資料加入 DB 並取得 ID
    db.add_all([p1, p2, p3, l1])
    db.commit()

    # 3. 建立學生資料 (並綁定指導教授 p1)
    s1 = models.Student(
        student_id="M11402165", 
        student_name="趙祈佑", 
        thesis_title_zh="智慧口試佈告生成系統", 
        thesis_title_en="Defense-Bot",
        advisor_professor_id=p1.professor_id
    )
    db.add(s1)
    db.commit()

    print("✅ 測試資料已成功灌入 SQLite 資料庫 (data/defense.db)！")
    db.close()

if __name__ == "__main__":
    run_seed()    