import type { GuideStep } from './guideData'

export const joinFamilyGuide: { title: string; label: string; introduction: string; steps: GuideStep[] } = {
  title: 'איך מצטרפים למשפחה קיימת?',
  label: 'הצטרפות למשפחה קיימת',
  introduction: 'צילומי המסך מציגים את אפליקציות iPhone ו־Android במצב כהה.',
  steps: [
    { title: 'בחירת הצטרפות למשפחה', paragraphs: ['במסך הפתיחה של Family Car Agent, לחצו על ״הצטרפות למשפחה״.'], screenshot: { src: '/assets/guides/join-family/step-1.jpg', alt: 'מסך הפתיחה ב־iPhone עם כפתור הצטרפות למשפחה', width: 591, height: 1280 } },
    { title: 'התחברות לחשבון', paragraphs: ['התחברו באמצעות האפשרות המתאימה למכשיר שלכם:'], platformNotes: ['iPhone: ניתן להתחבר באמצעות Google או Apple.', 'Android: ההתחברות מתבצעת באמצעות Google.'], screenshot: { src: '/assets/guides/join-family/step-2.jpg', alt: 'התחברות ב־iPhone באמצעות Google או Apple', width: 591, height: 1280 } },
    { title: 'הזנת שם המשפחה', paragraphs: ['הזינו את שם המשפחה שאליה אתם רוצים להצטרף, בדיוק כפי שהוא מוגדר באפליקציה.'], screenshot: { src: '/assets/guides/join-family/step-3.jpg', alt: 'מסך Android להזנת שם המשפחה הקיימת', width: 575, height: 1280 } },
    { title: 'אימות כתובת המשפחה', paragraphs: ['הזינו את כתובת המגורים של המשפחה, כולל עיר, רחוב ומספר בית.', 'בדקו את הכתובת שהמערכת מצאה ואשרו אותה. אם היא אינה נכונה, בחרו באפשרות לשנות אותה.'], screenshot: { src: '/assets/guides/join-family/step-4.jpg', alt: 'מסך Android להזנת כתובת הבית של המשפחה', width: 575, height: 1280 } },
    { title: 'הזנת קוד המשפחה', paragraphs: ['הזינו את קוד המשפחה שקיבלתם.', 'תוכלו למצוא אותו אצל מנהל המשפחה, במסך ״משפחה״ שבדשבורד, או בהודעת ההצטרפות שנשלחה אליכם.'], screenshot: { src: '/assets/guides/join-family/step-5.jpg', alt: 'מסך Android להזנת קוד המשפחה', width: 575, height: 1280 } },
    { title: 'השלמת ההצטרפות', paragraphs: ['הזינו את שמכם הפרטי, קראו ואשרו את הסעיף המשפטי ולחצו על ״הצטרפות למשפחה״.', 'לאחר מכן יופיע מסך אישור ההצטרפות. לחצו על כפתור ההמשך — וזהו, אתם חלק מהמשפחה!'], screenshot: { src: '/assets/guides/join-family/step-6.jpg', alt: 'מסך Android עם שם פרטי, הסעיף המשפטי וכפתור הצטרפות למשפחה', width: 575, height: 1280 } },
  ],
}
