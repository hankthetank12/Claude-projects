(function () {
  var items = Array.prototype.slice.call(document.querySelectorAll("li.item"));
  var left = document.getElementById("remaining");

  function refresh() {
    var open = 0;
    var spend = 0;
    items.forEach(function (li) {
      var box = li.querySelector("input");
      if (box && !box.checked) {
        open += 1;
        spend += parseFloat(li.dataset.cost || "0");
      }
      li.classList.toggle("done", box && box.checked);
    });
    if (left) {
      left.textContent = open + " left · about $" + spend.toFixed(2) + " to go";
    }
  }

  items.forEach(function (li) {
    var box = li.querySelector("input");
    if (box) box.addEventListener("change", refresh);
  });

  var copy = document.getElementById("copy");
  if (copy) {
    copy.addEventListener("click", function () {
      var lines = items
        .filter(function (li) {
          var box = li.querySelector("input");
          return box && !box.checked;
        })
        .map(function (li) {
          return li.dataset.plain || "";
        });
      var text = lines.join("\n");
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          copy.textContent = "Copied";
          setTimeout(function () { copy.textContent = "Copy list"; }, 1500);
        });
      }
    });
  }

  refresh();
})();
