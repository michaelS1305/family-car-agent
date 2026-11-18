import { GuideNavigation } from './GuidePage'
import type { GuideStep } from './guideData'

const category = 'הזמנת רכב'
const categoryPath = '/support/bookings'
type BookingGuide = { path: string; title: string; label: string; category: string; categoryPath: string; introduction: string; steps: GuideStep[]; screenshot?: NonNullable<GuideStep['screenshot']> }
export const bookingGuides: BookingGuide[] = [
  {
    path: `${categoryPath}/chat`, title: 'איך מזמינים רכב דרך הסוכן החכם?', label: 'הזמנת רכב דרך הסוכן החכם', category, categoryPath,
    introduction: 'המדריך מיועד למשתמשי Android ו־iPhone.',
    screenshot: { src: '/assets/guides/bookings/chat.jpg', alt: 'שיחה עם הסוכן החכם: בקשת הזמנת רכב והשלמת טווח הזמן', width: 575, height: 1280 },
    steps: [
      { title: 'פתיחת הצ’אט', paragraphs: ['היכנסו למסך ״צ’אט״ באפליקציה וכתבו לסוכן החכם שאתם רוצים להזמין רכב.'] },
      { title: 'מסירת פרטי ההזמנה', paragraphs: ['ציינו איזה רכב תרצו להזמין, במיוחד אם למשפחה יש כמה רכבים.', 'ציינו גם את טווח הזמן המבוקש:'], choices: ['מועד התחלה.', 'מועד סיום.'], trailingParagraphs: ['אפשר למסור את כל הפרטים בהודעה אחת.', 'אם חסר מידע, הסוכן ישאל שאלות להשלמת ההזמנה.'] },
      { title: 'אישור ההזמנה', paragraphs: ['אם הרכב פנוי בטווח הזמן שביקשתם, הסוכן יבצע את ההזמנה ויודיע לכם בצ’אט.', 'אם כבר קיימת הזמנה חופפת לאותו רכב, לא ניתן להזמין אותו לאותו טווח זמן.', 'כל הקודם להזמין — זוכה!'] },
    ],
  },
  {
    path: `${categoryPath}/manage`, title: 'איך מנהלים את מרכז ההזמנות?', label: 'ניהול מרכז ההזמנות', category, categoryPath,
    introduction: 'המדריך מיועד למשתמשי Android ו־iPhone.',
    steps: [
      { title: 'צפייה בהזמנות בלוח השנה', paragraphs: ['היכנסו למסך ״מרכז ההזמנות״ דרך הדשבורד.', 'בחרו תאריך בלוח השנה כדי לצפות בהזמנות של אותו יום.', 'נקודה כחולה מתחת לתאריך מסמנת שקיימות בו הזמנות.'], screenshot: { src: '/assets/guides/bookings/calendar.jpg', alt: 'מרכז ההזמנות: בחירת תאריך, נקודת הזמנה כחולה וחלונית תחתונה', width: 575, height: 1280 } },
      { title: 'צפייה בפרטי ההזמנות', paragraphs: ['החליקו את החלונית התחתונה כלפי מעלה כדי להרחיב אותה ולצפות בפרטי ההזמנות.', 'תוכלו לראות את הרכב, המשתמש וטווח השעות של כל הזמנה.'], screenshot: { src: '/assets/guides/bookings/details.jpg', alt: 'חלונית ההזמנות המורחבת עם הרכב, המשתמש ושעות ההזמנה', width: 575, height: 1280 } },
      { title: 'שימוש בסרגל הפעולות', paragraphs: ['סרגל הפעולות מאפשר לנהל את ההזמנות.', 'מימין לשמאל:'], orderedChoices: ['סינון — פתיחת חלונית לסינון ההזמנות.', 'עריכה — בחירת הזמנה קיימת ועריכת פרטיה.', 'מחיקה — בחירת הזמנה וביטולה.', 'הוספה — פתיחת חלונית ליצירת הזמנה חדשה.', 'חזרה להיום — איפוס התאריך הנבחר לתאריך הנוכחי.'], screenshot: { src: '/assets/guides/bookings/toolbar.jpg', alt: 'תקריב סרגל הפעולות, מימין לשמאל: סינון, עריכה, מחיקה, הוספה וחזרה להיום', width: 921, height: 262 } },
      { title: 'הרשאות לעריכה ולביטול', paragraphs: ['ניתן לצפות בהזמנות של בני המשפחה.'], permission: 'עם זאת, אפשר לערוך או לבטל רק הזמנות שאתם יצרתם בעצמכם.' },
    ],
  },
]

export function BookingGuidesPage() {
  return <div className="guides-page section-inner"><GuideNavigation listing category={category} categoryPath={categoryPath} /><header className="guide-heading"><p className="guide-eyebrow">מדריכים</p><h1>{category}</h1></header><div className="guide-list">{bookingGuides.map(guide => <a key={guide.path} className="guide-list-card" href={guide.path}><h2>{guide.label}</h2><p>{guide.title}</p><span>למדריך המלא ←</span></a>)}</div><a className="guide-back" href="/support">חזרה למרכז התמיכה</a></div>
}
