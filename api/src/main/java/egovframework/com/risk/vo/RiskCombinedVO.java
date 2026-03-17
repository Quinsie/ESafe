package egovframework.com.risk.vo;

import java.io.Serializable;

/**
 * 종합위험점수 VO (VW_RISK_COMBINED 매핑)
 */
public class RiskCombinedVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /* 건물 기본 */
    private long bldgSeq;
    private String branchNm;
    private String a0;           // 건물고유번호
    private String a13;          // 건물명
    private String a17;          // 건축물 구조명
    private String a19;          // 주요용도명
    private String structureName;
    private String mainUseName;
    private String regionNm;
    private String districtNm;
    private String regionCd;
    private String addr;
    private double lon;
    private double lat;
    private Integer buildYear;
    private Integer buildAge;
    private String completionDate;

    /* 정적점수 */
    private String ageGrade;
    private int ageScore;
    private String floodGrade;
    private int floodScore;
    private Double landslideDistance;
    private String landslideGrade;
    private int landslideScore;
    private int fireScore;
    private String prevFireOccurDate;
    private int landUseScore;
    private int facilityRiskScore;
    private double totalScore;
    private String totalGrade;
    private String riskCd;

    /* 기상점수 */
    private String riskDate;
    private double weatherScore;
    private double wildfireScore;
    private String appliedAlerts;

    /* 합산 */
    private double combinedScore;
    private String combinedRiskCd;
    private String combinedGradeNm;
    private String gradeChangedYn;

    /* 시스템 */
    private String analDate;
    private String regDt;

    /* --- 통계용 필드 --- */
    private int bldgCnt;
    private double avgTotalScore;
    private double avgWeatherScore;
    private double avgCombinedScore;
    private double maxCombinedScore;
    private int gradeE;
    private int gradeD;
    private int gradeC;
    private int gradeB;
    private int gradeA;
    private int gradeChangedCnt;
    private int dangerCnt;  // 위험이상(D+E)

    // ===== Getters & Setters =====

    public long getBldgSeq() { return bldgSeq; }
    public void setBldgSeq(long bldgSeq) { this.bldgSeq = bldgSeq; }

    public String getBranchNm() { return branchNm; }
    public void setBranchNm(String branchNm) { this.branchNm = branchNm; }

    public String getA0() { return a0; }
    public void setA0(String a0) { this.a0 = a0; }

    public String getA13() { return a13; }
    public void setA13(String a13) { this.a13 = a13; }

    public String getA17() { return a17; }
    public void setA17(String a17) { this.a17 = a17; }

    public String getA19() { return a19; }
    public void setA19(String a19) { this.a19 = a19; }

    public String getStructureName() { return structureName; }
    public void setStructureName(String structureName) { this.structureName = structureName; }

    public String getMainUseName() { return mainUseName; }
    public void setMainUseName(String mainUseName) { this.mainUseName = mainUseName; }

    public String getRegionNm() { return regionNm; }
    public void setRegionNm(String regionNm) { this.regionNm = regionNm; }

    public String getDistrictNm() { return districtNm; }
    public void setDistrictNm(String districtNm) { this.districtNm = districtNm; }

    public String getRegionCd() { return regionCd; }
    public void setRegionCd(String regionCd) { this.regionCd = regionCd; }

    public String getAddr() { return addr; }
    public void setAddr(String addr) { this.addr = addr; }

    public double getLon() { return lon; }
    public void setLon(double lon) { this.lon = lon; }

    public double getLat() { return lat; }
    public void setLat(double lat) { this.lat = lat; }

    public Integer getBuildYear() { return buildYear; }
    public void setBuildYear(Integer buildYear) { this.buildYear = buildYear; }

    public Integer getBuildAge() { return buildAge; }
    public void setBuildAge(Integer buildAge) { this.buildAge = buildAge; }

    public String getCompletionDate() { return completionDate; }
    public void setCompletionDate(String completionDate) { this.completionDate = completionDate; }

    public String getAgeGrade() { return ageGrade; }
    public void setAgeGrade(String ageGrade) { this.ageGrade = ageGrade; }

    public int getAgeScore() { return ageScore; }
    public void setAgeScore(int ageScore) { this.ageScore = ageScore; }

    public String getFloodGrade() { return floodGrade; }
    public void setFloodGrade(String floodGrade) { this.floodGrade = floodGrade; }

    public int getFloodScore() { return floodScore; }
    public void setFloodScore(int floodScore) { this.floodScore = floodScore; }

    public Double getLandslideDistance() { return landslideDistance; }
    public void setLandslideDistance(Double landslideDistance) { this.landslideDistance = landslideDistance; }

    public String getLandslideGrade() { return landslideGrade; }
    public void setLandslideGrade(String landslideGrade) { this.landslideGrade = landslideGrade; }

    public int getLandslideScore() { return landslideScore; }
    public void setLandslideScore(int landslideScore) { this.landslideScore = landslideScore; }

    public int getFireScore() { return fireScore; }
    public void setFireScore(int fireScore) { this.fireScore = fireScore; }

    public String getPrevFireOccurDate() { return prevFireOccurDate; }
    public void setPrevFireOccurDate(String prevFireOccurDate) { this.prevFireOccurDate = prevFireOccurDate; }

    public int getLandUseScore() { return landUseScore; }
    public void setLandUseScore(int landUseScore) { this.landUseScore = landUseScore; }

    public int getFacilityRiskScore() { return facilityRiskScore; }
    public void setFacilityRiskScore(int facilityRiskScore) { this.facilityRiskScore = facilityRiskScore; }

    public double getTotalScore() { return totalScore; }
    public void setTotalScore(double totalScore) { this.totalScore = totalScore; }

    public String getTotalGrade() { return totalGrade; }
    public void setTotalGrade(String totalGrade) { this.totalGrade = totalGrade; }

    public String getRiskCd() { return riskCd; }
    public void setRiskCd(String riskCd) { this.riskCd = riskCd; }

    public String getRiskDate() { return riskDate; }
    public void setRiskDate(String riskDate) { this.riskDate = riskDate; }

    public double getWeatherScore() { return weatherScore; }
    public void setWeatherScore(double weatherScore) { this.weatherScore = weatherScore; }

    public double getWildfireScore() { return wildfireScore; }
    public void setWildfireScore(double wildfireScore) { this.wildfireScore = wildfireScore; }

    public String getAppliedAlerts() { return appliedAlerts; }
    public void setAppliedAlerts(String appliedAlerts) { this.appliedAlerts = appliedAlerts; }

    public double getCombinedScore() { return combinedScore; }
    public void setCombinedScore(double combinedScore) { this.combinedScore = combinedScore; }

    public String getCombinedRiskCd() { return combinedRiskCd; }
    public void setCombinedRiskCd(String combinedRiskCd) { this.combinedRiskCd = combinedRiskCd; }

    public String getCombinedGradeNm() { return combinedGradeNm; }
    public void setCombinedGradeNm(String combinedGradeNm) { this.combinedGradeNm = combinedGradeNm; }

    public String getGradeChangedYn() { return gradeChangedYn; }
    public void setGradeChangedYn(String gradeChangedYn) { this.gradeChangedYn = gradeChangedYn; }

    public String getAnalDate() { return analDate; }
    public void setAnalDate(String analDate) { this.analDate = analDate; }

    public String getRegDt() { return regDt; }
    public void setRegDt(String regDt) { this.regDt = regDt; }

    public int getBldgCnt() { return bldgCnt; }
    public void setBldgCnt(int bldgCnt) { this.bldgCnt = bldgCnt; }

    public double getAvgTotalScore() { return avgTotalScore; }
    public void setAvgTotalScore(double avgTotalScore) { this.avgTotalScore = avgTotalScore; }

    public double getAvgWeatherScore() { return avgWeatherScore; }
    public void setAvgWeatherScore(double avgWeatherScore) { this.avgWeatherScore = avgWeatherScore; }

    public double getAvgCombinedScore() { return avgCombinedScore; }
    public void setAvgCombinedScore(double avgCombinedScore) { this.avgCombinedScore = avgCombinedScore; }

    public double getMaxCombinedScore() { return maxCombinedScore; }
    public void setMaxCombinedScore(double maxCombinedScore) { this.maxCombinedScore = maxCombinedScore; }

    public int getGradeE() { return gradeE; }
    public void setGradeE(int gradeE) { this.gradeE = gradeE; }

    public int getGradeD() { return gradeD; }
    public void setGradeD(int gradeD) { this.gradeD = gradeD; }

    public int getGradeC() { return gradeC; }
    public void setGradeC(int gradeC) { this.gradeC = gradeC; }

    public int getGradeB() { return gradeB; }
    public void setGradeB(int gradeB) { this.gradeB = gradeB; }

    public int getGradeA() { return gradeA; }
    public void setGradeA(int gradeA) { this.gradeA = gradeA; }

    public int getGradeChangedCnt() { return gradeChangedCnt; }
    public void setGradeChangedCnt(int gradeChangedCnt) { this.gradeChangedCnt = gradeChangedCnt; }

    public int getDangerCnt() { return dangerCnt; }
    public void setDangerCnt(int dangerCnt) { this.dangerCnt = dangerCnt; }
}
