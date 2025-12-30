addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url)
  
  if (url.hostname === 'www.pceawendaniacademy.co.ke') {
    url.hostname = 'pceawendaniacademy.co.ke'
    return Response.redirect(url.toString(), 301)
  }
  
  return fetch(request)
}