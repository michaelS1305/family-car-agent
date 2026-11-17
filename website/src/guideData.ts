export type GuideStep = {
  title: string
  paragraphs: string[]
  platformNotes?: string[]
  choices?: string[]
  orderedChoices?: string[]
  trailingParagraphs?: string[]
  permission?: string
  screenshot?: { src: string; alt: string; width?: number; height?: number }
}

export const createFamilyGuide: { title: string; steps: GuideStep[] } = {
  title: 'איך יוצרים משפחה ב־Family Car Agent?',
  steps: [
    { title: 'התחלת יצירת המשפחה', paragraphs: ['במסך הפתיחה של האפליקציה, לחצו על ״יצירת משפחה״.'], screenshot: { src: '/assets/guides/create-family/step-1.jpg', alt: 'מסך הפתיחה ב־iPhone עם כפתור יצירת משפחה' } },
    { title: 'התחברות לחשבון', paragraphs: ['בחרו את אפשרות ההתחברות המתאימה למכשיר:'], platformNotes: ['iPhone: התחברות באמצעות Google או Apple.', 'Android: התחברות באמצעות Google בלבד.'], screenshot: { src: '/assets/guides/create-family/step-2.jpg', alt: 'מסך ההתחברות ב־iPhone עם אפשרויות Google ו־Apple' } },
    { title: 'בחירת שם למשפחה', paragraphs: ['הזינו את שם המשפחה הרצוי ולחצו על ״המשך״.'], screenshot: { src: '/assets/guides/create-family/step-3.jpg', alt: 'שדה שם המשפחה וכפתור המשך' } },
    { title: 'הגדרת כתובת הבית', paragraphs: ['הזינו את כתובת המגורים, כולל עיר, רחוב ומספר בית.', 'לאחר מכן בדקו את הכתובת שהמערכת מציגה ואשרו אותה. אם היא אינה תואמת, תוכלו לשנות אותה.'], screenshot: { src: '/assets/guides/create-family/step-4.jpg', alt: 'מסך הזנת כתובת הבית: עיר, רחוב ומספר בית' } },
    { title: 'השלמת הפרטים', paragraphs: ['הזינו את שמכם הפרטי, קראו ואשרו את הסעיף המשפטי ולחצו על ״יצירת המשפחה״.'], screenshot: { src: '/assets/guides/create-family/step-5.jpg', alt: 'שם פרטי, אישור הסעיף המשפטי וכפתור יצירת המשפחה' } },
    { title: 'סיום ההרשמה', paragraphs: ['לאחר יצירת המשפחה יופיע מסך הצלחה עם קוד המשפחה.', 'לחצו על ״הלאה״ כדי להמשיך לאפליקציה.'] },
  ],
}
