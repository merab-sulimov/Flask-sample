# api language example requests


### To get all languages for the user ID #1:

Request:

```bash
curl "http://localhost:5000/api/account/1/language" -b session=95e6cc42-4041-4cfb-bfe0-880107b07a75 -H "X-Requested-With: xmlhttprequest"

```

Response:

```
{"data":[{"id":1,"language_level":3,"language_name":"English"}],"meta":{"levels":[[0,"Basic"],[1,"Conversational"],[2,"Fluent"],[3,"Native or Bilingual"]],"total":1}}
```

----


### To create new language item for logged user:

Request:

```bash
curl -d 'language_name=English&language_level=3' "http://localhost:5000/api/account/language" -b session=95e6cc42-4041-4cfb-bfe0-880107b07a75 -H "X-Requested-With: xmlhttprequest"
```

Response:

```
if error:
{"error":{"message":"You already have this language"}}

if ok:
{} 
```

### To delete language from logged user:
Request:

```
curl -d '{"id": 1}'  "http://localhost:5000/api/account/language/delete" -b session=95e6cc42-4041-4cfb-bfe0-880107b07a75 -H "X-Requested-With: xmlhttprequest" -H "Content-Type: application/json"

```

Response:

```
{}
```

----


### To update recommended flag for product:

```
curl -d '{"recommend": true}'  "http://localhost:5000/api/admin/products/1/recommend" -b session=95e6cc42-4041-4cfb-bfe0-880107b07a75 -H "X-Requested-With: xmlhttprequest" -H "Content-Type: application/json"
```

