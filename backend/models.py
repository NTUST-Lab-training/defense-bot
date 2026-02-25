from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base

class Professor(Base):
    __tablename__ = "professors"

    # 【修正】改成 String，以支援 "P001" 這種 ID
    professor_id = Column(String, primary_key=True, index=True)
    professor_name = Column(String, index=True, nullable=False)
    professor_title = Column(String, nullable=False)
    department_name = Column(String, nullable=False)

    # 關聯：一個教授可以指導多個學生
    students = relationship("Student", back_populates="advisor")

class Student(Base):
    __tablename__ = "students"

    # 學號有英文字母 (e.g., M11402165)，保持 String
    student_id = Column(String, primary_key=True, index=True) 
    student_name = Column(String, nullable=False)
    thesis_title_zh = Column(String)
    thesis_title_en = Column(String)
    
    #  advisor_id 對齊 CSV，型別為 String 對齊 Professor
    advisor_id = Column(String, ForeignKey("professors.professor_id"))

    # 關聯
    advisor = relationship("Professor", back_populates="students")
    defense_logs = relationship("DefenseLog", back_populates="student")

class DefenseLocation(Base):
    __tablename__ = "defense_locations"

    #  String，以支援 "L001" 這種 ID
    location_id = Column(String, primary_key=True, index=True)
    building_name = Column(String)
    room_number = Column(String)
    full_location_name = Column(String, nullable=False)

    # 關聯
    defense_logs = relationship("DefenseLog", back_populates="location")

class DefenseLog(Base):
    __tablename__ = "defense_logs"

    # log_id 用 Integer (自動遞增) 是沒問題的
    log_id = Column(Integer, primary_key=True, index=True)
    location_full_text = Column(String, default="")
    student_id = Column(String, ForeignKey("students.student_id"))
    
    # String 對齊 DefenseLocation
    location_id = Column(String, ForeignKey("defense_locations.location_id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    defense_date_text = Column(String, nullable=False)
    defense_time_text = Column(String, nullable=False)
    committee_json = Column(String, nullable=False) # 陣列存成 JSON 字串
    generated_file_url = Column(String)

    # 關聯
    student = relationship("Student", back_populates="defense_logs")
    location = relationship("DefenseLocation", back_populates="defense_logs")