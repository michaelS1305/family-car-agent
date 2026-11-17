import { GuidePage, GuideNavigation } from './GuidePage'
import type { GuideStep } from './guideData'

const category = 'ניהול רכבים'
const categoryPath = '/support/vehicles'
type VehicleGuide = { path: string; label: string; title: string; steps: GuideStep[]; notes?: string[]; video?: boolean; soon?: boolean }
const shot = (name: string, alt: string) => ({ src: `/assets/guides/vehicles/${name}.jpg`, alt, width: 591, height: 1280 })
export const vehicleGuides: VehicleGuide[] = [
  {
    path: `${categoryPath}/add`, label: 'הוספת רכב למשפחה', title: 'איך מוסיפים רכב למשפחה?',
    steps: [
      { title: 'הגדרת הרכב הראשון', paragraphs: ['כשנכנסים לאפליקציה בפעם הראשונה ולמשפחה עדיין אין רכבים, תופיע חלונית המזמינה את מנהל המשפחה להוסיף רכב ולהגדיר את החיבור שלו.', 'לחצו על ״להגדרה״ כדי לעבור למסך הרכבים.'], screenshot: shot('invitation', 'חלונית ההזמנה להגדרת הרכב הראשון עם כפתור להגדרה') },
      { title: 'הוספת רכב', paragraphs: ['במסך ״רכבים״, לחצו על ״הוספת רכב״.', 'אם כבר קיימים רכבים במשפחה, תוכלו להוסיף רכב נוסף באמצעות סמל +.'], screenshot: shot('empty', 'מסך הרכבים ללא רכבים וכפתור הוספת רכב') },
      { title: 'מילוי פרטי הרכב', paragraphs: ['במסך ״הוספת רכב״, מלאו את הפרטים:'], choices: ['שם הרכב — הכינוי שבו תרצו לזהות אותו במשפחה.', 'סוג הרכב — בחרו את האיור המתאים.', 'יצרן הרכב.', 'דגם הרכב.', 'מספר הרישוי.'], trailingParagraphs: ['לאחר מילוי הפרטים, לחצו על ״הוספת רכב״ לשמירה.'], screenshot: shot('add', 'טופס הוספת רכב: שם, איור, יצרן, דגם ומספר רכב') },
      { title: 'הרכב נוסף למשפחה', paragraphs: ['לאחר השמירה, הרכב יופיע ברשימת ״הרכבים שלנו״ במסך הרכבים.', 'תוכלו ללחוץ עליו כדי להיכנס למסך פרטי הרכב ולהמשיך בהגדרת החיבור והזיהוי האוטומטי.'], screenshot: shot('list', 'הרכב שנוסף מופיע ברשימת הרכבים שלנו') },
    ],
    notes: ['רק מנהל המשפחה רשאי להוסיף, לערוך או למחוק רכבים.', 'שאר בני המשפחה יכולים לצפות ברכבים ולהשתמש ביכולות הזמינות להם.'],
  },
  {
    path: `${categoryPath}/manage`, label: 'ניהול פרטי רכב וטיפולים', title: 'איך מנהלים פרטי רכב וטיפולים?',
    steps: [
      { title: 'כניסה למסך הרכב', paragraphs: ['היכנסו למסך ״רכבים״ בדשבורד ובחרו את הרכב שתרצו לנהל מתוך רשימת ״הרכבים שלנו״.'], permission: 'כל בני המשפחה.', screenshot: shot('list', 'רשימת הרכבים שלנו לבחירת הרכב לניהול') },
      { title: 'צפייה במצב הרכב', paragraphs: ['במסך הרכב תוכלו לראות את מצבו הנוכחי, למשל אם הוא ״פנוי״, ולגשת למידע ולפעולות הקשורות אליו.'], permission: 'כל בני המשפחה.', screenshot: shot('details', 'פרטי הרכב: מצב פנוי, חיבור אוטומטי, טיפולים ופרטי רכב') },
      { title: 'חיבור וזיהוי אוטומטי', paragraphs: ['לחצו על ״חיבור וזיהוי אוטומטי״ כדי לעבור להגדרות החיבור של הרכב.', 'תהליך ההגדרה מוסבר במדריך נפרד בהתאם למערכת ההפעלה.'], permission: 'כל בני המשפחה.' },
      { title: 'ניהול טיפולים ותחזוקה', paragraphs: ['באזור ״טיפולים״ תוכלו לצפות בטיפולים שנוספו לרכב.', 'מנהל המשפחה יכול ללחוץ על סמל + כדי להוסיף טיפול חדש.', 'הרשאות:'], choices: ['צפייה — כל בני המשפחה.', 'הוספת טיפול — מנהל המשפחה בלבד.'] },
      { title: 'עריכת פרטי הרכב', paragraphs: ['באזור ״פרטי רכב״, לחצו על סמל העיפרון כדי לערוך את פרטי הרכב השמורים.', 'הרשאות:'], choices: ['צפייה — כל בני המשפחה.', 'עריכה — מנהל המשפחה בלבד.'] },
    ],
  },
  {
    path: `${categoryPath}/android-connection`, label: 'זיהוי וחיבור אוטומטי — Android', title: 'איך מגדירים זיהוי וחיבור אוטומטי ב־Android?', video: true,
    steps: [
      { title: 'כניסה למסך הרכבים', paragraphs: ['היכנסו למסך ״רכבים״ דרך הדשבורד.'] },
      { title: 'בחירת הרכב', paragraphs: ['בחרו את הרכב שתרצו לחבר.'] },
      { title: 'פתיחת הגדרות החיבור', paragraphs: ['לחצו על ״זיהוי וחיבור אוטומטי״.'] },
      { title: 'רישום הרכב', paragraphs: ['בצעו את שלב רישום הרכב בהתאם להוראות באפליקציה.'] },
      { title: 'בחירת Bluetooth', paragraphs: ['בחרו את חיבור ה־Bluetooth המתאים לרכב.'] },
      { title: 'הרשאות מיקום', paragraphs: ['ודאו שבהגדרות Android:'], choices: ['הרשאת המיקום מוגדרת ל־״מותר כל הזמן״.', 'האפשרות ״מיקום מדויק״ מופעלת.'], trailingParagraphs: ['לאחר השלמת ההגדרה, האפליקציה תוכל להשתמש בחיבור שנבחר לזיהוי הרכב.'] },
    ],
  },
  { path: `${categoryPath}/iphone-carplay`, label: 'זיהוי וחיבור — iPhone CarPlay', title: 'זיהוי וחיבור אוטומטי — iPhone CarPlay', soon: true, steps: [] },
  { path: `${categoryPath}/iphone-bluetooth`, label: 'זיהוי וחיבור — iPhone Bluetooth', title: 'זיהוי וחיבור אוטומטי — iPhone Bluetooth', soon: true, steps: [] },
]

export function VehicleGuidesPage() {
  return <div className="guides-page section-inner"><GuideNavigation listing category={category} categoryPath={categoryPath} /><header className="guide-heading"><p className="guide-eyebrow">מדריכים</p><h1>{category}</h1></header><div className="guide-list">{vehicleGuides.map(g => <a className="guide-list-card" href={g.path} key={g.path}><h2>{g.label}{g.soon && ' — בקרוב'}</h2><span>{g.soon ? 'מדריך הווידאו יעלה בקרוב' : 'למדריך המלא ←'}</span></a>)}</div><a className="guide-back" href="/support">חזרה למרכז התמיכה</a></div>
}

export function VehicleGuidePage({ guide }: { guide: VehicleGuide }) {
  const media = guide.video ? <figure className="guide-video"><video controls playsInline preload="none" aria-label="מדריך וידאו להגדרת חיבור אוטומטי לרכב ב־Android" aria-describedby="vehicle-video-description" src="/assets/guides/vehicles/android-connection.mov">הדפדפן אינו תומך בהצגת וידאו.</video><figcaption id="vehicle-video-description">הדגמת הגדרת חיבור אוטומטי ב־Android. ההוראות הכתובות מופיעות בהמשך. <a href="/assets/guides/vehicles/android-connection.mov">פתיחת הסרטון המקורי</a></figcaption></figure> : guide.soon ? <div className="guide-coming-soon"><p>בקרוב</p><p>מדריך הווידאו יעלה בקרוב</p></div> : undefined
  return <GuidePage {...guide} category={category} categoryPath={categoryPath} introduction={guide.soon ? '' : guide.video ? 'מדריך למשתמשי Android.' : 'המדריך מיועד למשתמשי Android ו־iPhone.'} media={media} />
}
