import './NotFoundPage.css'
export default function NotFoundPage() {
 return <section className="not-found" aria-labelledby="not-found-title">
  <img className="not-found-cloud" src="/assets/not-found-cloud.webp" alt="" width="143" height="69" />
  <div className="not-found-number" aria-hidden="true">404</div>
  <h1 id="not-found-title">העמוד לא נמצא</h1>
  <p>נראה שהעמוד שחיפשת לא קיים או שהועבר.</p>
  <img className="not-found-art" src="/assets/not-found-illustration.webp" alt="משפחה במכונית על דרך מתפתלת ליד שלט עם סימן שאלה" width="1536" height="285" />
  <div className="not-found-actions"><a className="button button-primary" href="/">חזרה לדף הבית <span aria-hidden="true">⌂</span></a><a className="button button-secondary" href="/support">למרכז התמיכה</a></div>
 </section>
}
