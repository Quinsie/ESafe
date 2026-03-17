package egovframework.com.risk.vo;

import java.io.Serializable;

/**
 * 기상특보/기상점수 VO
 */
public class RiskWeatherVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /* TB_WEATHER_ALERT */
    private long alertSeq;
    private String alertDate;
    private String alertType;
    private String alertLevel;
    private String alertCmd;
    private String regionNm;
    private String regionCd;
    private String parentRegion;
    private String issueDt;
    private String effectDt;
    private String cancelNote;

    /* TB_WEATHER_RISK */
    private long riskSeq;
    private String riskDate;
    private String districtNm;
    private double weatherScore;
    private double wildfireScore;
    private String wildfireGrade;
    private String wildfireTm;
    private String appliedAlerts;

    /* 통계용 */
    private int cnt;
    private int regionCnt;
    private double avgWeatherScore;
    private double maxWeatherScore;
    private int scoreRegionCnt;

    // ===== Getters & Setters =====

    public long getAlertSeq() { return alertSeq; }
    public void setAlertSeq(long alertSeq) { this.alertSeq = alertSeq; }

    public String getAlertDate() { return alertDate; }
    public void setAlertDate(String alertDate) { this.alertDate = alertDate; }

    public String getAlertType() { return alertType; }
    public void setAlertType(String alertType) { this.alertType = alertType; }

    public String getAlertLevel() { return alertLevel; }
    public void setAlertLevel(String alertLevel) { this.alertLevel = alertLevel; }

    public String getAlertCmd() { return alertCmd; }
    public void setAlertCmd(String alertCmd) { this.alertCmd = alertCmd; }

    public String getRegionNm() { return regionNm; }
    public void setRegionNm(String regionNm) { this.regionNm = regionNm; }

    public String getRegionCd() { return regionCd; }
    public void setRegionCd(String regionCd) { this.regionCd = regionCd; }

    public String getParentRegion() { return parentRegion; }
    public void setParentRegion(String parentRegion) { this.parentRegion = parentRegion; }

    public String getIssueDt() { return issueDt; }
    public void setIssueDt(String issueDt) { this.issueDt = issueDt; }

    public String getEffectDt() { return effectDt; }
    public void setEffectDt(String effectDt) { this.effectDt = effectDt; }

    public String getCancelNote() { return cancelNote; }
    public void setCancelNote(String cancelNote) { this.cancelNote = cancelNote; }

    public long getRiskSeq() { return riskSeq; }
    public void setRiskSeq(long riskSeq) { this.riskSeq = riskSeq; }

    public String getRiskDate() { return riskDate; }
    public void setRiskDate(String riskDate) { this.riskDate = riskDate; }

    public String getDistrictNm() { return districtNm; }
    public void setDistrictNm(String districtNm) { this.districtNm = districtNm; }

    public double getWeatherScore() { return weatherScore; }
    public void setWeatherScore(double weatherScore) { this.weatherScore = weatherScore; }

    public double getWildfireScore() { return wildfireScore; }
    public void setWildfireScore(double wildfireScore) { this.wildfireScore = wildfireScore; }

    public String getWildfireGrade() { return wildfireGrade; }
    public void setWildfireGrade(String wildfireGrade) { this.wildfireGrade = wildfireGrade; }

    public String getWildfireTm() { return wildfireTm; }
    public void setWildfireTm(String wildfireTm) { this.wildfireTm = wildfireTm; }

    public String getAppliedAlerts() { return appliedAlerts; }
    public void setAppliedAlerts(String appliedAlerts) { this.appliedAlerts = appliedAlerts; }

    public int getCnt() { return cnt; }
    public void setCnt(int cnt) { this.cnt = cnt; }

    public int getRegionCnt() { return regionCnt; }
    public void setRegionCnt(int regionCnt) { this.regionCnt = regionCnt; }

    public double getAvgWeatherScore() { return avgWeatherScore; }
    public void setAvgWeatherScore(double avgWeatherScore) { this.avgWeatherScore = avgWeatherScore; }

    public double getMaxWeatherScore() { return maxWeatherScore; }
    public void setMaxWeatherScore(double maxWeatherScore) { this.maxWeatherScore = maxWeatherScore; }

    public int getScoreRegionCnt() { return scoreRegionCnt; }
    public void setScoreRegionCnt(int scoreRegionCnt) { this.scoreRegionCnt = scoreRegionCnt; }
}
