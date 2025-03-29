(function() {
  const dateFormat = new Intl.DateTimeFormat("en-US",
    {minute:'numeric', hour:'numeric', day:'numeric', month:'long', timeZone: "Asia/Kolkata"});
  document.querySelectorAll('.date').
    forEach(d => {
      const date = dateFormat.format(new Date(d.dataset.date));
      d.textContent = date;
    })
}())
