export const canonicalOrigin = 'https://familycaragent.com'
const brand = 'Family Car Agent'
export const pages: Record<string, { title: string; description: string; index?: boolean }> = {
 '/': {title: 'הדרך החכמה למשפחה', description: 'ניהול רכבים, הזמנות ותיאום בין בני המשפחה — במקום אחד.'},
 '/terms': {title: 'תנאי שימוש', description: 'תנאי השימוש של Family Car Agent, גרסה 1.2: חשבון, ניהול משפחה ורכבים, מחיקה וזכויות המשתמש.'},
 '/privacy': {title: 'מדיניות פרטיות', description: 'מדיניות הפרטיות של Family Car Agent, גרסה 1.2: איסוף מידע, עיבוד, שיתוף, שמירה ומחיקה.'},
 '/features': {title: 'יכולות האפליקציה', description: 'ניהול משפחתי משותף, עדכונים בזמן אמת וטיפולים ותחזוקה לרכבי המשפחה.'},
 '/support': {title: 'מרכז התמיכה', description: 'מדריכים ושאלות נפוצות על משפחה, רכבים, הזמנות והגדרות האפליקציה.'},
 '/contact': {title: 'יצירת קשר', description: 'פנייה לצוות התמיכה עם שאלה, תקלה, הצעה או חוות דעת.'},
 '/support/family': {title: 'מדריכי ניהול משפחה', description: 'יצירת משפחה, הצטרפות למשפחה קיימת וניהול מסך המשפחה.'},
 '/support/family/create': {title: 'איך יוצרים משפחה ב־Family Car Agent?', description: 'מדריך ליצירת משפחה: התחברות, שם המשפחה, כתובת הבית והשלמת הפרטים.'},
 '/support/family/join': {title: 'איך מצטרפים למשפחה קיימת?', description: 'מדריך להצטרפות למשפחה באמצעות שם המשפחה, כתובתה וקוד המשפחה.'},
 '/support/family/manage': {title: 'איך מנהלים את מסך המשפחה?', description: 'הזמנת בני משפחה, כתובת, קוד משפחתי ותפקידים — עם פירוט הרשאות.'},
 '/support/settings': {title: 'מדריכי הגדרות והתראות', description: 'הגדרות iPhone ו־Android, התראות, מצב תצוגה ומחיקת חשבון.'},
 '/support/settings/iphone': {title: 'הגדרות, התראות ומצב תצוגה — iPhone', description: 'מצב תצוגה, הרשאות מיקום והתראות וגישה להגדרות חיבור הרכב באייפון.'},
 '/support/settings/android': {title: 'הגדרות, התראות ומצב תצוגה — Android', description: 'מצב תצוגה, מיקום מדויק, התראות וחיבור הרכב באמצעות Android Companion.'},
 '/support/settings/delete-account': {title: 'מחיקת חשבון ועזיבת משפחה', description: 'פתיחת בקשת מחיקה, קריאת ההשלכות ובדיקת השלמת המחיקה ב־Android וב־iPhone.'},
 '/support/bookings': {title: 'מדריכי הזמנת רכב', description: 'הזמנת רכב דרך הסוכן החכם וניהול מרכז ההזמנות.'},
 '/support/bookings/chat': {title: 'איך מזמינים רכב דרך הסוכן החכם?', description: 'מסירת הרכב וטווח הזמן בצ׳אט, השלמת פרטים ובדיקת זמינות להזמנה.'},
 '/support/bookings/manage': {title: 'איך מנהלים את מרכז ההזמנות?', description: 'לוח השנה, פרטי ההזמנות, סרגל הפעולות והרשאות עריכה וביטול.'},
 '/support/vehicles': {title: 'מדריכי ניהול רכבים', description: 'הוספת רכב, פרטי רכב וטיפולים, וחיבור אוטומטי ב־Android. מדריכי iPhone יעלו בהמשך.'},
 '/support/vehicles/add': {title: 'איך מוסיפים רכב למשפחה?', description: 'הוספת רכב ראשון או נוסף, מילוי פרטי הרכב ושמירתו במשפחה.'},
 '/support/vehicles/manage': {title: 'איך מנהלים פרטי רכב וטיפולים?', description: 'צפייה במצב הרכב, גישה לחיבור אוטומטי, טיפולים ועריכת פרטים לפי הרשאות.'},
 '/support/vehicles/android-connection': {title: 'איך מגדירים זיהוי וחיבור אוטומטי ב־Android?', description: 'מדריך וידאו והוראות לבחירת הרכב, רישומו, Bluetooth והרשאות מיקום.'},
 '/support/vehicles/iphone-carplay': {title: 'זיהוי וחיבור אוטומטי — iPhone CarPlay', description: 'מדריך הווידאו לחיבור iPhone CarPlay יעלה בקרוב.', index: false},
 '/support/vehicles/iphone-bluetooth': {title: 'זיהוי וחיבור אוטומטי — iPhone Bluetooth', description: 'מדריך הווידאו לחיבור iPhone Bluetooth יעלה בקרוב.', index: false},
}
export function pageMetadata(pathname: string) {
 const path = pathname.replace(/\/+$/, '') || '/'
 const page = pages[path]
 return {
  title: page ? (page.title.includes(brand) ? page.title : `${page.title} | ${brand}`) : `העמוד לא נמצא | ${brand}`,
  description: page?.description ?? 'נראה שהעמוד שחיפשת לא קיים או שהועבר.',
  canonical: page ? canonicalOrigin + path : null,
  robots: page && page.index !== false ? 'index,follow' : 'noindex,follow',
  image: canonicalOrigin + '/assets/fca-road-logo.png',
 }
}
export function metadataEntries(path: string) {
 const m = pageMetadata(path)
 return [
  ['name', 'description', m.description], ['name', 'robots', m.robots],
  ['property', 'og:title', m.title], ['property', 'og:description', m.description],
  ['property', 'og:type', 'website'], ['property', 'og:locale', 'he_IL'],
  ['property', 'og:image', m.image], ['property', 'og:image:alt', 'Family Car Agent'],
  ...(m.canonical ? [['property', 'og:url', m.canonical]] : []),
 ]
}
export function applyPageMetadata(doc: Document, path: string) {
 const m = pageMetadata(path)
 doc.title = m.title
 doc.querySelectorAll('[data-site-seo]').forEach(node => node.remove())
 for (const [attribute, key, value] of metadataEntries(path)) {
  const node = doc.createElement('meta')
  node.setAttribute(attribute, key); node.content = value
  node.setAttribute('data-site-seo', ''); doc.head.appendChild(node)
 }
 if (m.canonical) {
  const link = doc.createElement('link'); link.rel = 'canonical'; link.href = m.canonical
  link.setAttribute('data-site-seo', ''); doc.head.appendChild(link)
 }
}
