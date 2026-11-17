import { GuideNavigation } from './GuidePage'
import type { GuideStep } from './guideData'

const category = 'הגדרות והתראות'
const categoryPath = '/support/settings'
type SettingsGuide = { path: string; title: string; label: string; introduction: string; category: string; categoryPath: string; steps: GuideStep[]; screenshot: NonNullable<GuideStep['screenshot']>; notes?: string[] }
export const settingsGuides: SettingsGuide[] = [
  {
    path: `${categoryPath}/iphone`, title: 'הגדרות, התראות ומצב תצוגה — iPhone', label: 'הגדרות iPhone', category, categoryPath,
    introduction: 'הגדרות האפליקציה ב־iPhone.',
    screenshot: { src: '/assets/guides/settings/iphone.jpg', alt: 'הגדרות iPhone: תצוגה, מיקום, התראות וזיהוי וחיבור אוטומטי', width: 591, height: 1280 },
    steps: [
      { title: 'שינוי מצב התצוגה', paragraphs: ['היכנסו למסך ״הגדרות״ באפליקציה.', 'באזור ״תצוגה״ בחרו את המצב הרצוי:'], choices: ['מערכת — האפליקציה מתאימה את התצוגה למצב שמוגדר באייפון.', 'בהיר — האפליקציה תוצג תמיד במצב בהיר.', 'כהה — האפליקציה תוצג תמיד במצב כהה.'] },
      { title: 'הרשאת מיקום', paragraphs: ['באזור ״הרשאות״, לחצו על ״מיקום״ כדי לפתוח את הגדרות המיקום של האפליקציה באייפון.', 'כדי לאפשר את פעולת הזיהוי האוטומטי, הגדירו את הרשאת המיקום ל־״תמיד״.'] },
      { title: 'הרשאות התראות', paragraphs: ['לחצו על ״התראות״ באזור ההרשאות.', 'ייפתחו הגדרות ההתראות של Family Car Agent באייפון.', 'ודאו שהאפשרות ״אפשר התראות״ מופעלת, כדי לקבל עדכונים מהאפליקציה.'] },
      { title: 'זיהוי וחיבור אוטומטי', paragraphs: ['לחצו על ״זיהוי וחיבור אוטומטי״ כדי לעבור למסך הרכבים.', 'שם תוכלו לבחור רכב ולנהל את הגדרות החיבור והקיצורים שלו.'] },
    ],
  },
  {
    path: `${categoryPath}/android`, title: 'הגדרות, התראות ומצב תצוגה — Android', label: 'הגדרות Android', category, categoryPath,
    introduction: 'הגדרות האפליקציה ב־Android.',
    screenshot: { src: '/assets/guides/settings/android.jpg', alt: 'הגדרות Android: תצוגה, מיקום, התראות ו־Android Companion', width: 575, height: 1280 },
    steps: [
      { title: 'שינוי מצב התצוגה', paragraphs: ['היכנסו למסך ״הגדרות״ באפליקציה.', 'באזור ״תצוגה״ בחרו את המצב הרצוי:'], choices: ['מערכת — האפליקציה מתאימה את התצוגה להגדרות המכשיר.', 'בהיר — האפליקציה תוצג תמיד במצב בהיר.', 'כהה — האפליקציה תוצג תמיד במצב כהה.'] },
      { title: 'הרשאת מיקום', paragraphs: ['באזור ״הרשאות״, לחצו על ״מיקום״ כדי לפתוח את הגדרות ההרשאה של Android.', 'כדי שהזיהוי האוטומטי יפעל כראוי, ודאו שהמיקום מוגדר:'], choices: ['מותר כל הזמן.', 'מיקום מדויק מופעל.'] },
      { title: 'הרשאות התראות', paragraphs: ['לחצו על ״התראות״ כדי לפתוח את הגדרות ההתראות של האפליקציה ב־Android.', 'ודאו שההתראות מופעלות, כדי לקבל עדכונים על פעילות הרכבים והמשפחה.'] },
      { title: 'Android Companion / זיהוי וחיבור', paragraphs: ['במסך ההגדרות של Android, לחצו על ״Android Companion״.', 'האפשרות תעביר אתכם למסך הרכבים, שבו תוכלו לבחור רכב ולהגדיר את הזיהוי והחיבור האוטומטי שלו.'] },
    ],
  },
  {
    path: `${categoryPath}/delete-account`, title: 'מחיקת חשבון ועזיבת משפחה', label: 'מחיקת חשבון ועזיבת משפחה', category, categoryPath,
    introduction: 'מדריך משותף ל־iPhone ול־Android. צילום המסך מתוך iPhone.',
    screenshot: { src: '/assets/guides/settings/delete-account.jpg', alt: 'אפשרות מחיקת חשבון בתחתית מסך הגדרות ב־iPhone', width: 591, height: 1280 },
    steps: [
      { title: 'פתיחת מחיקת החשבון', paragraphs: ['היכנסו למסך ״הגדרות״, גללו לתחתית ולחצו על ״מחיקת חשבון״.'] },
      { title: 'קריאת פרטי המחיקה ואישור', paragraphs: ['תיפתח חלונית אישור המציגה מידע על מחיקת החשבון והשלכותיה.', 'קראו את הפרטים בעיון.', 'אם החלטתם להמשיך, אשרו את בקשת המחיקה.'] },
      { title: 'בדיקת השלמת המחיקה', paragraphs: ['Android:', 'לאחר האישור תוצג חלונית שבה ניתן לבדוק את מצב מחיקת החשבון.', 'iPhone:', 'לאחר האישור ייפתח מסך ייעודי לבדיקת מצב המחיקה.', 'המתינו מספר שניות, לחצו על כפתור בדיקת המצב וודאו שהמחיקה אושרה והושלמה.'] },
    ],
    notes: ['מחיקת החשבון היא גם הדרך לעזוב את המשפחה. הפעולה מוחקת את החשבון עצמו, ולא רק את השיוך המשפחתי.', 'אם מנהל המשפחה מוחק את חשבונו, האחריות לניהול עוברת לבן משפחה אחר.'],
  },
]

export function SettingsGuidesPage() {
  return <div className="guides-page section-inner"><GuideNavigation listing category={category} categoryPath={categoryPath} /><header className="guide-heading"><p className="guide-eyebrow">מדריכים</p><h1>{category}</h1></header><div className="guide-list">{settingsGuides.map(guide => <a key={guide.path} className="guide-list-card" href={guide.path}><h2>{guide.title}</h2><span>למדריך המלא ←</span></a>)}</div><a className="guide-back" href="/support">חזרה למרכז התמיכה</a></div>
}
